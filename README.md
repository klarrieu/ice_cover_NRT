# Near-real-time (NRT) Sea Ice Cover Maps
Server script to download, process, and serve near-real-time sea ice cover data from S-NPP VIIRS ([VNP29_NRT](https://modaps.modaps.eosdis.nasa.gov/services/about/products/viirs-land-c1-nrt/VNP29_NRT.html)) with 375m resolution. This tool has the following features:

- Set custom area of interest (AOI) and date range for data query and download
- Filter datasets by AOI coverage, day/night observations
- Compute coverage of data classes within AOI
- Identify best datasets with minimal cloud cover
- produce ice cover maps as `uint8` rasters for small and portable output file sizes
- Generate composite ice cover maps, combining cloud-free regions of multiple observations to make more comprehensive ice cover maps
- Automatically send email notifications with ice cover maps

## Prerequisites
A Python environment is required with the following packages:
- earthaccess
- geopandas
- h5py
- scipy
- rasterio

For data access, an account is required with [NASA Earthdata](https://urs.earthdata.nasa.gov/users/new).

To send email notifications with ice cover maps, an account setup with the [Gmail Python API](https://developers.google.com/gmail/api/quickstart/python) is also required.

## Installation
```
git clone https://github.com/klarrieu/ice_cover_NRT.git
cd ice_cover_NRT
```

## Running

1. Create a `config` subdirectory with the following files:
    - `email_recipients.txt`: plain text file, each line corresponding to an email address for receiving updates.
    - `credendials.json`: Gmail API credentials

2. Open `serve_ice.py` and set desired date range and AOI in the script, as well as sender email address.

3. `python serve_ice.py` will run the script. The first time it runs will require authentication of the Earthdata API, after which credentials will be stored in a `~/.netrc` file. The script can then be setup to run periodically (e.g. as a cronjob for a server).

That's all there is to it for now. If you find this useful, have any issues, or suggested additional features, please feel free to reach out or open an issue/PR.


## Data codes
| Code | Description        |
|------|--------------------|
| 0    | open water         |
| 1    | sea ice            |
| 200  | missing            |
| 201  | no decision        |
| 211  | night              |
| 225  | land               |
| 237  | inland water       |
| 250  | cloud              |
| 252  | unusable L1B       |
| 253  | bowtie trim        |
| 254  | missing L1B        |
