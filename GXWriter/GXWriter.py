# Author:   Ronoaldo JLP 
# Date:     May 24, 2020
# Description:  This plugin generates and inserts code including a image of the
#               slices part.

from UM.Mesh.MeshWriter import MeshWriter
from UM.MimeTypeDatabase import MimeTypeDatabase, MimeType
from cura.Snapshot import Snapshot
from cura.Utils.Threading import call_on_qt_thread
from UM.Logger import Logger
from UM.Scene.SceneNode import SceneNode #For typing.
from UM.PluginRegistry import PluginRegistry
from UM.i18n import i18nCatalog
catalog = i18nCatalog("cura")

import re
from io import StringIO, BufferedIOBase #To write the g-code to a temporary buffer, and for typing.
from typing import cast, List
from . import gx

def getValue(line, key, default=None):
    if key not in line:
        return default
    else:
        subPart = line[line.find(key) + len(key):]
        m = re.search('^-?[0-9]+\\.?[0-9]*', subPart)
    try:
        return float(m.group(0))
    except:
        return default

class GXWriter(MeshWriter):

    def __init__(self):
        super().__init__(add_to_recent_files = False)
        self._snapshot = None
        MimeTypeDatabase.addMimeType(
            MimeType(
                name = "application/xgcode",
                comment = "GX (xgcode)",
                suffixes = ["gx"],
            )
        )

    @call_on_qt_thread 
    def write(self, stream, nodes: List[SceneNode], mode = MeshWriter.OutputMode.BinaryMode) -> bool:
        Logger.log("i", "Starting GXWriter.")
        if mode != MeshWriter.OutputMode.BinaryMode:
            Logger.log("e", "GXWriter does not support non-text mode.")
            self.setInformation(catalog.i18nc("@error:not supported", "GXWriter does not support non-text mode."))
            return False
        # Render in-memory gcode
        gcode_textio = StringIO() #We have to convert the g-code into bytes.
        gcode_writer = cast(MeshWriter, PluginRegistry.getInstance().getPluginObject("GCodeWriter"))
        success = gcode_writer.write(gcode_textio, None)
        # If gcode fails, we can't proceed.
        if not success: 
            self.setInformation(gcode_writer.getInformation())
            return False
        # Mofify gcode adding gx header binary information and image preview.
        result=self.modify(gcode_textio.getvalue())
        stream.write(result)
        Logger.log("i", "GXWriter done")
        return True

    def modify(self, gcode):
        try:
            # Initialize GX header variables
            g = gx.GX()
            g.gcode = gcode.encode('latin-1')
            # Parse values from original gcode
            self._parse_gcode_info(g, gcode)
            # TODO(ronoaldo): insert the grayscale bitmap into image
            self._createSnapshot()
            g.bmp = b"".join([b"\x00" for x in range(14454)])
            return g.encode()
        except Exception:
            Logger.logException("w", "\n\n\n\n*** Failed to create gx file, defaulting to write gcode!!! ***\n\n\n")
            return gcode.encode('latin-1')

    def _parse_gcode_info(self, gx, gcode):
        for line in gcode.split("\n"):
            if line.startswith(';TIME:'):
                gx.print_time = int(getValue(line, ';TIME:', 0))
            if line.startswith(';Filament used:'):
                f = float(line.split(':')[1].split('m')[0].strip())
                f = f*100
                gx.filament_usage = int(f)
            if line.startswith(';Layer height:'):
                f = float(getValue(line, ';Layer height:', 0))
                f = f*1000
                gx.layer_height = int(f)
        Logger.log("i", "Updated values from struct =>", vars(gx))

    def _createSnapshot(self, *args):
        Logger.log("i", "Creating thumbnail image ...")
        try:
            self._snapshot = Snapshot.snapshot(width = 60, height = 60)
            Logger.log("i", "self._snapshot => ", dir(self._snapshot))
        except Exception:
            Logger.logException("w", "Failed to create snapshot image")
            self._snapshot = None  

    def generate_image_code(self, image,startX=0, startY=0, endX=60, endY=60):
        MAX_PIC_WIDTH_HEIGHT = 320
        width = image.width()
        height = image.height()
        if endX > width:
            endX = width
        if endY > height:
            endY = height
        scale = 1.0
        max_edge = endY - startY
        if max_edge < endX - startX:
            max_edge = endX - startX
        if max_edge > MAX_PIC_WIDTH_HEIGHT:
            scale = MAX_PIC_WIDTH_HEIGHT / max_edge
        if scale != 1.0:
            width = int(width * scale)
            height = int(height * scale)
            startX = int(startX * scale)
            startY = int(startY * scale)
            endX = int(endX * scale)
            endY = int(endY * scale)
            image = image.scaled(width, height)
        res_list = []
        for i in range(startY, endY):
            for j in range(startX, endX):
                res_list.append(image.pixel(j, i))

        index_pixel = 0
        pixel_num = 0
        pixel_data = ''
        pixel_string=""
        pixel_string+=('M4010 X%d Y%d\n' % (endX - startX, endY - startY))
        last_color = -1
        mask = 32
        unmask = ~mask
        same_pixel = 1
        color = 0
        for j in res_list:
            a = j >> 24 & 255
            if not a:
                r = g = b = 255
            else:
                r = j >> 16 & 255
                g = j >> 8 & 255
                b = j & 255
            color = (r >> 3 << 11 | g >> 2 << 5 | b >> 3) & unmask
            if last_color == -1:
                last_color = color
            elif last_color == color and same_pixel < 4095:
                same_pixel += 1
            elif same_pixel >= 2:
                pixel_data += '%04x' % (last_color | mask)
                pixel_data += '%04x' % (12288 | same_pixel)
                pixel_num += same_pixel
                last_color = color
                same_pixel = 1
            else:
                pixel_data += '%04x' % last_color
                last_color = color
                pixel_num += 1
            if len(pixel_data) >= 180:
                pixel_string+=("M4010 I%d T%d '%s'\n" % (index_pixel, pixel_num, pixel_data))
                pixel_data = ''
                index_pixel += pixel_num
                pixel_num = 0

        if same_pixel >= 2:
            pixel_data += '%04x' % (last_color | mask)
            pixel_data += '%04x' % (12288 | same_pixel)
            pixel_num += same_pixel
            last_color = color
            same_pixel = 1
        else:
            pixel_data += '%04x' % last_color
            last_color = color
            pixel_num += 1
        pixel_string+=("M4010 I%d T%d '%s'\n" % (index_pixel, pixel_num, pixel_data))
        return pixel_string

