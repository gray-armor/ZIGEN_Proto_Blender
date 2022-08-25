# ##### BEGIN GPL LICENSE BLOCK #####
#
# A script for Blender to import the CamTrackAR Camera and Anchor data
# Copyright (C) 2020 FXhome Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

bl_info = {
    "name": "Import: HitFilm AR App Composite (.hfcs)",
    "description": "Import AR tracking data (camera, anchor points) recorded by the FXhome HitFilm AR App.",
    "author": "FXhome Ltd.",
    "version": (1, 2, 1),
    "blender": (2, 80, 0),
    "location": "File > Import > HitFilm AR Tracking Data (.hfcs)",
    "warning": "", # used for warning icon and text in addons panel
#    "wiki_url": "http://wiki.blender.org/index.php/Extensions:2.6/Py/"
#                "Scripts/My_Script",
#    "support": "COMMUNITY",
    "category": "Import-Export",
}

import bpy
import math
import mathutils
import xml.etree.ElementTree as ET
from bpy_extras.io_utils import axis_conversion

PixelsPerMM = 2.8352

def zoomToLens(lensZoomInPixels, compWidthInPixels):
    lensZoomInMM = lensZoomInPixels / PixelsPerMM
    compWidthInMM = compWidthInPixels / PixelsPerMM
    lens = (36.0 * lensZoomInMM) / compWidthInMM # 36mm is the default sensor size in Blender
    return lens

def calculateFOV(lensZoomInPixels, compHeightInPixels):
    lensZoomInMM = lensZoomInPixels / PixelsPerMM
    compHeightInMM = compHeightInPixels / PixelsPerMM

    fov = math.atan((compHeightInMM * 0.5) / lensZoomInMM) * 2.0
    print(math.degrees(fov))
    return fov

def import_hitfilm_composite(context, filepath):
    C = context
    O = bpy.ops

    tree = ET.parse(filepath)
    root = tree.getroot()

    ### Global Scene Settings

    avSettingsNode = root.find(".//*AudioVideoSettings")
    width = int(avSettingsNode.find("Width").text)
    height = int(avSettingsNode.find("Height").text)
    frameRate = int(avSettingsNode.find("FrameRate").text)
    C.scene.render.resolution_x = width
    C.scene.render.resolution_y = height
    C.scene.render.fps = frameRate

    cameraNode = root.find(".//*CameraLayer")
    if cameraNode is None:
        print("Unable to find CameraLayer in Composite")
        return {'CANCELLED'}
    
    ### Import the Camera and Animation

    timeKeys = []
    camPositions = []
    camRotations = []
    camZoomVals = []

    cameraPosAnim = cameraNode.findall(".//*position/Animation")
    if len(cameraPosAnim) > 0:
        print("----- Camera Position Data -----")
        posKeys = list(cameraPosAnim[0])
        for key in posKeys:
            timeKeys.append(key.get('Time'))
            position = key.find('.//*FXPoint3_32f')
            camPositions.append( (float(position.get('X')), float(position.get('Y')), float(position.get('Z'))) )

    cameraRotationAnim = cameraNode.findall(".//*orientation/Animation")
    if len(cameraRotationAnim) > 0:
        print("----- Camera Rotation Data -----")
        rotationKeys = list(cameraRotationAnim[0])
        assert len(timeKeys) == len(rotationKeys) # Must match the timings already recorded for Position Data
        for key in rotationKeys:
            euler = key.find('.//*Orientation3D')
            camRotations.append( (float(euler.get('X')), float(euler.get('Y')), float(euler.get('Z'))) )

    cameraZoomAnim = cameraNode.findall(".//*zoom/Animation")
    if len(cameraZoomAnim) > 0:
        print("----- Camera Zoom Data -----")
        zoomKeys = list(cameraZoomAnim[0])
        assert len(timeKeys) == len(zoomKeys) # Must match the timings already recorded for Position Data
        for key in zoomKeys:
            zoom = key.find('Value/float').text
            camZoomVals.append(float(zoom))

    # Set the animation length
    C.scene.frame_end = len(timeKeys)

    # Rescale to Blender coordinates 
    blenderScale = (1.0 / 1000.0) * PixelsPerMM # number of pixels per mm

    # Transform required for HF to Blender coordinate system
    mToZUp = axis_conversion(from_forward='Z', from_up='Y', to_forward='-Y', to_up='Z').to_4x4()

    # Add the Camera
    O.object.camera_add(enter_editmode=False)
    cameraObject = C.active_object
    cameraObject.data.display_size = 0.2
    cameraObject.name = "ARCamera"

    for i in range(len(timeKeys)):
        C.scene.frame_set(i)

        # Zoom to Lens
        cameraObject.data.lens = zoomToLens(camZoomVals[i], width)
        cameraObject.data.keyframe_insert("lens", frame=i)

        # Rotation
        orientation = mathutils.Vector(camRotations[i]) 
        # Remember, orientations were inverted on export for HF, so invert again here for Blender.
        eul = mathutils.Euler(tuple([-math.radians(elem) for elem in orientation]), "ZYX") # Degrees to Radians

        # Location
        location = mathutils.Vector(camPositions[i])
        location = tuple([blenderScale * elem for elem in location]) # Rescale to Blender units

        mat_rot = eul.to_matrix() # Rotation Matrix (3x3)
        mat_loc = mathutils.Matrix().Translation(location) # Translation Matrix (4x4)
        mat = mat_loc @ mat_rot.to_4x4() # World Transform

        cameraObject.matrix_world = mToZUp @ mat

        O.anim.keyframe_insert_menu(type='BUILTIN_KSI_LocRot')

    C.scene.frame_set(0)

    ### Import the Anchor Points
    anchorNodes = root.findall(".//*PointLayer")
    for anchorNode in anchorNodes:
        anchorName = anchorNode.find(".//*Name")
        positionNode = anchorNode.find(".//*position/Default/p3")
        vec = (float(positionNode.get('X')), float(positionNode.get('Y')), float(positionNode.get('Z')))
        location = mathutils.Vector(vec)
        location = tuple([blenderScale * elem for elem in location]) # Rescale to Blender units
        O.object.empty_add(type='ARROWS', location=location)
        anchorObject = C.active_object
        anchorObject.name = anchorName.text
        anchorObject.matrix_world = mToZUp @ anchorObject.matrix_world
        anchorObject.rotation_euler.x = anchorObject.rotation_euler.x - math.radians(90)
        anchorObject.empty_display_size = 0.1

    return {'FINISHED'}


# ImportHelper is a helper class, defines filename and
# invoke() function which calls the file selector.
from bpy_extras.io_utils import ImportHelper
from bpy.props import StringProperty, BoolProperty, EnumProperty
from bpy.types import Operator

class ImportHitFilmARComposite(Operator, ImportHelper):
    """Import HitFilm Composite Shots exported from FXhome AR App."""
    bl_idname = "hitfilm_import.import_composite"  # important since its how bpy.ops.import_test.some_data is constructed
    bl_label = "HitFilm (.hfcs)"

    # ImportHelper mixin class uses this
    filename_ext = ".hfcs"

    filter_glob: StringProperty(
        default="*.hfcs",
        options={'HIDDEN'},
        maxlen=255,  # Max internal buffer length, longer would be clamped.
    )

    def execute(self, context):
        return import_hitfilm_composite(context, self.filepath)

# Only needed if you want to add into a dynamic menu
def menu_func_import(self, context):
    self.layout.operator(ImportHitFilmARComposite.bl_idname, text="HitFilm AR Tracking Data (.hfcs)")

def register():
    bpy.utils.register_class(ImportHitFilmARComposite)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

def unregister():
    bpy.utils.unregister_class(ImportHitFilmARComposite)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)

# This allows you to run the script directly from Blender's Text editor
# to test the add-on without having to install it.
if __name__ == "__main__":
    register()