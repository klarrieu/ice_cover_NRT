import zipfile
import pickle
import os
from IceProcessor import IceProcessor
import SendMail as sm

if __name__ == "__main__":
    # set AOI bbox
    min_lat, min_lon = -75.25, -115.0
    max_lat, max_lon = -72.0, -100.0
    # instantiate processor
    ipr = IceProcessor(days=5, min_lat=min_lat, min_lon=min_lon, max_lat=max_lat, max_lon=max_lon, aoi_coverage=90)
    # query and filter datasets
    results = ipr.query_data()
    results = ipr.filter_results(results)
    # determine if we have new result/update
    update = True
    last_result_cache = "last_result.cache"
    if os.path.exists(last_result_cache):
        with open(last_result_cache, 'rb') as f:
            last_result = pickle.load(f)
        if last_result == results[-1]:
            print("No new datasets. Quitting.")
            update = False
    with open(last_result_cache, 'wb') as f:
        pickle.dump(results[-1], f)
    if update:
        # process into rasters, make composite
        raster, metadata = ipr.process_result_set(results)
        composite_raster = ipr.make_composite()

        # send out message
        print('Sending files...')
        # get mail service and list of recipients
        mail_service = sm.get_service()
        recipients = sm.get_recipients()
        print(f'Recipients: {", ".join(recipients)}')
        # create zip file of output raster, AOI stats metadata, composite raster
        zip_filename = "ice_cover.zip"
        with zipfile.ZipFile(zip_filename, "w") as zip:
            for f in [raster, f"{raster}.txt", composite_raster]:
                zip.write(f, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        # create message body text (AOI stats from output raster)
        message_text = "Most recent dataset stats:"
        for k, v in results[-1]['metadata'].items():
            message_text += f"\n\t{k}: {v}"
        for k, v in list(ipr.rasters.values())[0].items():
            message_text += f"\n\t{k}: {v:.2f}%"
        message_text += "\n\nClearest dataset stats:"
        for k, v in metadata.items():
            message_text += f"\n\t{k}: {v:.2f}%"
        # send the message
        message = sm.create_message_with_attachment(sender="thwaites.ice.server@gmail.com",
                                                    to=recipients,
                                                    subject='Ice Cover Maps',
                                                    message_text=message_text,
                                                    files=[zip_filename])
        res = sm.send_message(mail_service, "me", message)
        # email compressed tif with metadata stats to email list
        print('Done.')
