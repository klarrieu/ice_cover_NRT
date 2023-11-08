import earthaccess as ea
import datetime as dt
import numpy as np
import h5py
import os
import shutil
import json
from shapely.geometry import Polygon, Point
import geopandas as gpd
from scipy.interpolate import griddata
import rasterio
from rasterio.transform import from_origin


class IceProcessor(object):
    def __init__(self, product="VNP29_NRT", days=5,
                 min_lat=-75.25, min_lon=-115.0, max_lat=-72.0, max_lon=-100.0,
                 aoi_coverage=90):
        self.login()

        # product = 'MYD10_L2'  # MOD10_L2 Aqua and Terra
        # product = 'VNP29P1D'  # daily h5 grid
        # product = 'VNP29_NRT'  # near real-time nc file
        self.product = product

        # search between 5 days ago til tomorrow
        today = dt.date.today()
        date_range = (today - dt.timedelta(days=days), today + dt.timedelta(days=1))
        self.date_range = tuple(d.strftime("%Y-%m-%d") for d in date_range)
        print(f"Search date range: {self.date_range}")

        # set AOI bbox
        self.min_lat, self.min_lon = min_lat, min_lon
        self.max_lat, self.max_lon = max_lat, max_lon
        self.bbox = (self.min_lon, self.min_lat, self.max_lon, self.max_lat)
        print(f"Search bounding box: {self.bbox}")
        bbox_polygon = Polygon([(self.min_lon, self.min_lat), (self.min_lon, self.max_lat),
                                (self.max_lon, self.max_lat), (self.max_lon, self.min_lat)])
        self.bbox_polygon_projected = gpd.GeoSeries([bbox_polygon], crs="EPSG:4326").to_crs("EPSG:3031")[0]
        # minimum percent coverage when filtering results
        self.aoi_coverage = aoi_coverage

        # initialize raster properties and metadata
        self.rasters = {}
        self.in_crs = "EPSG:4326"                                       # WGS84
        self.out_crs = "EPSG:4326"                                      # TODO: EPSG:3031 Antarctic polar stereographic
        self.xmin, self.ymin, self.xmax, self.ymax = self.bbox          # bbox in output CRS
        self.xres, self.yres = 0.005, 0.001                             # x, y resolution in output CRS
        self.width = len(np.arange(self.xmin, self.xmax, self.xres))    # raster width
        self.height = len(np.arange(self.ymin, self.ymax, self.yres))   # raster height

    def login(self):
        try:
            ea.login(strategy="netrc")
            print('Logged in to Earthdata API.')
        except:
            ea.login(persist=True)

    def query_data(self):
        print('Searching for data...')
        results = ea.search_data(short_name=self.product,
                                 temporal=self.date_range,
                                 bounding_box=self.bbox)
        return results

    def filter_results(self, results):
        # filter to daytime results that cover certain percentage of bbox
        # daytime results
        results = [r for r in results if r['umm']['DataGranule']['DayNightFlag'] == 'Day']
        print(f"Daytime results: {len(results)}")
        # calculate extents and intersection with AOI
        extents = [r['umm']['SpatialExtent']['HorizontalSpatialDomain']['Geometry']['GPolygons'][0]['Boundary']['Points'] for r in results]
        extents = [Polygon([(p['Longitude'], p['Latitude']) for p in e[:4]]) for e in extents]
        extents_projected = gpd.GeoSeries(extents, crs="EPSG:4326").to_crs("EPSG:3031")
        intersection_areas = extents_projected.intersection(self.bbox_polygon_projected).area
        intersection_percents = intersection_areas / self.bbox_polygon_projected.area * 100
        results = [r for r, ip in zip(results, intersection_percents) if ip >= self.aoi_coverage]
        intersection_percents = [round(ip, 2) for ip in intersection_percents if ip >= self.aoi_coverage]
        print(f"Results with >{self.aoi_coverage}% AOI coverage: {len(results)}")
        # organize pertinent metadata for each file
        times = [r['umm']['TemporalExtent']['RangeDateTime']['EndingDateTime'] for r in results]
        metadata = {'Time': times, 'AOI percent coverage': intersection_percents}
        for i, r in enumerate(results):
            r['metadata'] = {}
            for k, v in metadata.items():
                r['metadata'][k] = v[i]
        if not len(results):
            raise Exception("No results after filtering.")
        return results

    def process_result_set(self, results):
        self.rasters = {}
        best_raster, best_metadata = None, None
        least_cc = 100
        results_copy = results.copy()
        while results_copy:
            result = results_copy.pop()
            # parse
            filepath = self.parse_and_download_result(result)
            raster, coverage_percents = self.hdf5_to_raster(filepath)
            self.rasters[raster] = coverage_percents
            # if downloaded file has mostly invalid data, go back to previous result from filtered list until we find a good one
            if coverage_percents['valid percentage'] > 70 and coverage_percents['clouds'] < least_cc:
                best_raster = raster
                best_metadata = coverage_percents
                least_cc = coverage_percents['clouds']
        print(f"\nBest raster: {best_raster}")
        print('AOI stats:')
        for k, v in best_metadata.items():
            print(f"\t{k}: {v:.2f}%")
        return best_raster, best_metadata

    def make_composite(self):
        print("\nMaking composite raster...")
        composite_filepath = "./rasters/composite.tif"
        composite = None
        for raster in self.rasters.keys():
            with rasterio.open(raster, 'r') as ds:
                arr = ds.read()
                if composite is None:
                    shutil.copyfile(raster, composite_filepath)
                    composite = arr
                else:
                    # if we don't already have open water or ice data,
                    # and arr is open water, ice, land, or inland water, use it
                    composite = np.where((composite != 0) & (composite != 1) &
                                         ((arr == 0) | (arr == 1) | (arr == 225) | (arr == 237)),
                                         arr,
                                         composite)
        with rasterio.open(composite_filepath, 'w', driver='GTiff', width=self.width, height=self.height,
                           count=1, dtype=composite.dtype, crs=self.out_crs,
                           transform=from_origin(self.xmin, self.ymin, self.xres, -self.yres)) as ds:
            ds.write(composite)
        print(f"Saved: {composite_filepath}")
        return composite_filepath

    def parse_and_download_result(self, result):
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
            ea.download(result, local_path='./nc_files/')
        return filepath

    def parse_hd5(self, filepath):
        # read the data
        print('Parsing data...')
        with h5py.File(filepath, 'r') as f:
            # print('Swath stats:')
            # for k in ['PercentOceanInSwath', 'CloudCoverOcean', 'ClearViewOcean', 'SeaIceCover']:
            #    print(f'\t{k}: {f.attrs[k].decode("utf-8")}')
            coords = f['GeolocationData']
            sea_ice_data = f['SeaIceCoverData']
            # get lat, lon, sea ice cover arrays
            lon = coords['longitude'][:].flatten()
            lat = coords['latitude'][:].flatten()
            ice_cover = sea_ice_data['SeaIceCover'][:].flatten()
            out_filename = f"./rasters/ice_cover_{f.attrs['EndTime'].decode('utf-8')}.tif"
        return lon, lat, ice_cover, out_filename

    def hdf5_to_raster(self, filepath):
        # read the data
        lon, lat, ice_cover, out_filename = self.parse_hd5(filepath)
        if os.path.exists(out_filename):
            print(f'Raster already exists: {out_filename}. Skipping...')
            coverage_percents = self.read_metadata(f"{out_filename}.txt")
        else:
            # crop to AOI (assuming AOI does not cross pole/prime meridian)
            arr = np.column_stack([lon, lat, ice_cover])
            arr = np.array([row for row in arr if (self.min_lon <= row[0] <= self.max_lon and
                                                   self.min_lat <= row[1] <= self.max_lat)])
            lon, lat, ice_cover = arr.T
            ice_cover = ice_cover.astype('uint8')
            # make geodataframe of points
            gdf = gpd.GeoDataFrame({'ice_cover': ice_cover},
                                   geometry=[Point(lon1, lat1) for lon1, lat1 in zip(lon, lat)], crs=self.in_crs)
            # interpolate to grid
            print('Interpolating to grid...')
            if self.in_crs != self.out_crs:
                gdf = gdf.to_crs(self.out_crs)
            x, y = np.meshgrid(np.arange(self.xmin, self.xmax, self.xres), np.arange(self.ymin, self.ymax, self.yres))
            # interpolated_values = griddata((gdf.geometry.x.values, gdf.geometry.y.values), gdf.ice_cover.values, (x,y), method='nearest')
            interpolated_values = griddata((lon, lat), ice_cover, (x,y), method='nearest')
            # check percent valid, percent of AOI in each class
            counts = gdf.groupby(['ice_cover']).count()
            open_count = counts.loc[0][0] if 0 in counts.index else 0
            ice_count = counts.loc[1][0] if 1 in counts.index else 0
            cloud_count = counts.loc[250][0] if 250 in counts.index else 0
            land_count = counts.loc[225][0] if 225 in counts.index else 0
            valid_count = open_count + ice_count + cloud_count + land_count
            coverage_percents = {'open water': open_count / valid_count * 100 if valid_count else 0,
                                 'ice cover': ice_count / valid_count * 100 if valid_count else 0,
                                 'clouds': cloud_count / valid_count * 100 if valid_count else 0,
                                 'land': land_count / valid_count * 100 if valid_count else 0,
                                 'valid percentage': valid_count / counts.sum()[0] * 100}
            print('AOI stats:')
            for k, v in coverage_percents.items():
                print(f"\t{k}: {v:.2f}%")
            # convert to raster
            print('Writing raster...')
            with rasterio.open(out_filename, 'w', driver='GTiff',
                               width=self.width, height=self.height,
                               count=1, dtype=interpolated_values.dtype, crs=self.out_crs,
                               transform=from_origin(self.xmin, self.ymin, self.xres, -self.yres)) as dst:
                dst.write(interpolated_values, 1)
            self.write_metadata(f"{out_filename}.txt", coverage_percents)
            print(f"Saved raster: {out_filename}")
        return out_filename, coverage_percents

    def write_metadata(self, filepath, metadata):
        with open(filepath, 'w') as f:
            f.write(json.dumps(metadata))

    def read_metadata(self, filepath):
        with open(filepath, 'r') as f:
            return json.load(f)
