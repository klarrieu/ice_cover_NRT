#!/bin/bash
source ~/miniforge3/etc/profile.d/conda.sh
conda activate geospatial
cd ~/ice_cover_NRT
nohup python -u serve_ice.py &> out.log &
