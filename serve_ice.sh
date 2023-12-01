#!/bin/bash
source ~/miniforge3/etc/profile.d/conda.sh
conda activate geospatial
cd ~/ice_cover_NRT
# get rid of old nc and raster files (to minimize storage space)
find ./nc_files/ -mtime +6 -delete
find ./rasters/ -mtime +6 -delete
nohup python -u serve_ice.py &> out.log &
