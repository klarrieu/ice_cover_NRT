import earthaccess as ea
import datetime as dt
import numpy as np
import h5py
import os
from shapely.geometry import Polygon, Point
import geopandas as gpd
from scipy.interpolate import griddata
import rasterio
from rasterio.transform import from_origin
import pdb


#product = 'VNP29P1D'  # daily h5 grid
product = 'VNP29_NRT'  # near real-time nc file

# search between 5 days ago til tomorrow
today = dt.date.today()
date_range = (today - dt.timedelta(days=5), today + dt.timedelta(days=1))
date_range = tuple(d.strftime("%Y-%m-%d") for d in date_range)
print(f"Search date range: {date_range}")

# set AOI bbox
min_lat, min_lon = -75.25, -115.0
max_lat, max_lon = -72.0, -100.0
bbox = (min_lon, min_lat, max_lon, max_lat)
print(f"Search bounding box: {bbox}")
bbox_polygon = Polygon([(min_lon, min_lat), (min_lon, max_lat), (max_lon, max_lat), (max_lon, min_lat)])
# minimum percent coverage when filtering results
aoi_coverage = 90


def filter_results(results):
    # filter to daytime results that cover certain percentage of bbox
    # daytime results
    results = [r for r in results if r['umm']['DataGranule']['DayNightFlag'] == 'Day']
    print(f"Daytime results: {len(results)}")
    # calculate extents and intersection with AOI
    extents = [r['umm']['SpatialExtent']['HorizontalSpatialDomain']['Geometry']['GPolygons'][0]['Boundary']['Points'] for r in results]
    extents = [Polygon([(p['Longitude'], p['Latitude']) for p in e[:4]]) for e in extents]
    extents_projected = gpd.GeoSeries(extents, crs="EPSG:4326").to_crs("EPSG:3031")
    bbox_polygon_projected = gpd.GeoSeries([bbox_polygon], crs="EPSG:4326").to_crs("EPSG:3031")[0]
    intersection_areas = extents_projected.intersection(bbox_polygon_projected).area
    intersection_percents = intersection_areas / bbox_polygon_projected.area * 100
    results = [r for r, ip in zip(results, intersection_percents) if ip >= aoi_coverage]
    intersection_percents = [round(ip, 2) for ip in intersection_percents if ip >= aoi_coverage]
    print(f"Results with >{aoi_coverage}% AOI coverage: {len(results)}")
    # organize pertinent metadata for each file
    times = [r['umm']['TemporalExtent']['RangeDateTime']['EndingDateTime'] for r in results]
    metadata = {'Time': times, 'AOI percent coverage': intersection_percents}
    for i, r in enumerate(results):
        r['metadata'] = {}
        for k, v in metadata.items():
            r['metadata'][k] = v[i]
    return results


def parse_and_download_result(result):
    print("\nGranule stats:")
    for k, v in result['metadata'].items():
        print(f"\t{k}: {v}")
    filename = result.data_links()[0].split('/')[-1]
    filepath = f'./nc_files/{filename}'
    # download the data
    if os.path.exists(filepath):
        # TODO: also make sure the file can be opened. Use checksum?
        print('File already downloaded, continuing...')
    else:
        # download = input('Download this result? y/n\n')
        download = 'y'
        download = True if download == 'y' else False
        if download:
            ea.download(result, local_path='./nc_files/')
    return filepath


def hdf5_to_raster(filepath):
    # read the data
    print('Parsing data...')
    with h5py.File(filepath, 'r') as f:
        #print('Swath stats:')
        #for k in ['PercentOceanInSwath', 'CloudCoverOcean', 'ClearViewOcean', 'SeaIceCover']:
        #    print(f'\t{k}: {f.attrs[k].decode("utf-8")}')
        coords = f['GeolocationData']
        sea_ice_data = f['SeaIceCoverData']
        # get lat, lon, sea ice cover arrays
        lon = coords['longitude'][:].flatten()
        lat = coords['latitude'][:].flatten()
        ice_cover = sea_ice_data['SeaIceCover'][:].flatten()
        # crop to AOI (assuming AOI does not cross pole/prime meridian)
        arr = np.column_stack([lon, lat, ice_cover])
        arr = np.array([row for row in arr if (row[0] >= min_lon and row[0] <= max_lon and row[1] >= min_lat and row[1] <= max_lat)])
        lon, lat, ice_cover = arr.T
        ice_cover = ice_cover.astype('uint8')
        # make geodataframe of points
        gdf = gpd.GeoDataFrame({'ice_cover': ice_cover}, geometry=[Point(lon1, lat1) for lon1, lat1 in zip(lon, lat)], crs="EPSG:4326")
        # interpolate to grid
        print('Interpolating to grid...')
        # gdf = gdf.to_crs("EPSG:3031")
        xmin, ymin, xmax, ymax = gdf.total_bounds
        #xres, yres = 375, 375
        xres, yres = 0.005, 0.001
        x, y = np.meshgrid(np.arange(xmin, xmax, xres), np.arange(ymin, ymax, yres))
        # interpolated_values = griddata((gdf.geometry.x.values, gdf.geometry.y.values), gdf.ice_cover.values, (x,y), method='nearest')
        interpolated_values = griddata((lon, lat), ice_cover, (x,y), method='nearest')
        # check percent valid, percent of AOI in each class
        counts = gdf.groupby(['ice_cover']).count()
        open_count = counts.loc[0][0] if 0 in counts.index else 0
        ice_count = counts.loc[1][0] if 1 in counts.index else 0
        cloud_count = counts.loc[250][0] if 250 in counts.index else 0
        land_count = counts.loc[225][0] if 225 in counts.index else 0
        valid_count  = open_count + ice_count + cloud_count + land_count
        percents = {'open water' : open_count / valid_count * 100 if valid_count else 0,
        	'ice cover': ice_count / valid_count * 100 if valid_count else 0,
        	'clouds': cloud_count / valid_count * 100 if valid_count else 0,
        	'land': land_count / valid_count * 100 if valid_count else 0,
        	'valid percentage': valid_count / counts.sum()[0] * 100}
        print('AOI stats:')
        for k, v in percents.items():
            print(f"\t{k}: {v:.2f}%")
        # convert to raster
        out_filename = f"./rasters/ice_cover_{f.attrs['EndTime'].decode('utf-8')}.tif"
        print('Writing raster...')
        with rasterio.open(out_filename, 'w', driver='GTiff', width=interpolated_values.shape[1], height=interpolated_values.shape[0], count=1, dtype=interpolated_values.dtype, crs=gdf.crs, transform=from_origin(xmin, ymin, xres, -yres)) as dst:
            dst.write(interpolated_values, 1)
        print(f"Saved raster: {out_filename}")
    return out_filename, percents



if __name__ == "__main__":
    # login to earthdata
    try:
        ea.login(strategy="netrc")
        print('Logged in to Earthdata API.')
    except:
        ea.login(persist=True)

    # query and filter search results
    print('Searching for data...')
    results = ea.search_data(short_name=product,
        temporal=date_range,
        bounding_box=bbox)
    results = filter_results(results)
    if not len(results):
        raise Exception("No results after filtering.")

    # TODO: keeping track of what we have already processed and sent
    rasters, metadata = [], []
    best_raster = None
    best_metadata = None
    while results:
        result = results.pop()
        # parse
        filepath = parse_and_download_result(result)
        raster, percents = hdf5_to_raster(filepath)
        rasters.append(raster)
        metadata.append(percents)
        # if downloaded file has mostly invalid data, go back to previous result from filtered list until we find a good one
        if percents['valid percentage'] > 70 and percents['clouds'] < 50:
            if best_raster is None:
                best_raster = raster
                best_metadata = percents
    # TODO: make composite ice cover raster
    # TODO: send out message
    # email compressed tif with metadata stats to email list
    print('Done.')
