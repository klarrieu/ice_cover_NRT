from IceProcessor import IceProcessor


if __name__ == "__main__":

    # set AOI bbox
    min_lat, min_lon = -75.25, -115.0
    max_lat, max_lon = -72.0, -100.0
    # instantiate processor
    ipr = IceProcessor(days=5, min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon, aoi_coverage=90)
    # query and filter datasets
    results = ipr.query_data()
    results = ipr.filter_results(results)
    # process into rasters, make composite
    raster, metadata = ipr.process_result_set(results)
    composite_raster = ipr.make_composite()

    # TODO: send out message
    # email compressed tif with metadata stats to email list
    print('Done.')
