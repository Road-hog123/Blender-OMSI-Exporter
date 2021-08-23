# OMSI Mesh Exporter for Blender

OMSI Mesh (`*.o3d`) exporter addon for
[Blender LTS](https://www.blender.org/download/lts/).

## Download and Installation

1. Download the latest release for your Blender version from the
[releases page](https://github.com/Road-hog123/blender-omsi-exporter/releases/).
2. Launch Blender and go to `Edit` > `Preferences` > `Add-ons` > `Install`.
Select the `.zip` file you downloaded, then click `Install Add-on`.
3. Check the checkbox next to the addon to enable it.

## Reporting Issues and Enhancements

If you encounter a bug, please report the issue to the
[issue tracker](https://github.com/road-hog123/blender-omsi-exporter/issues).
Enhancement suggestions also go to the issue tracker.

If the error message starts with `Traceback`, go to `Window` >
`Toggle System Console` and copy the message (up until a blank line) into the
bug report. You'll need to toggle the console off before you close Blender.

If applicable, please include a `.blend` file that can be used to reproduce the
issue and verify the fix.

## Usage

The exporter can be found at `File` > `Export` > `OMSI Mesh (.o3d)`. Like most
exporters, it exports the current selection - hidden objects and non-mesh
objects will be excluded.
