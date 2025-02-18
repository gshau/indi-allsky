#!/usr/bin/env python3

import time
from pathlib import Path
import argparse
import cv2
import numpy
from astropy.io import fits
import astroalign
import logging


astroalign.NUM_NEAREST_NEIGHBORS = 5
astroalign.PIXEL_TOL = 2


logging.basicConfig(level=logging.INFO)
logger = logging


class Align(object):
    def __init__(self, method):
        self.method = method

        self.transform = None


    def main(self, output, reference, inputfiles):
        reference_hdulist = fits.open(reference)

        hdulist_list = list()

        file_list = sorted([Path(x) for x in inputfiles], key=lambda p: p.stat().st_mtime)
        for i in file_list:
            filename_p = Path(i)

            hdulist = fits.open(filename_p)

            hdulist_list.append(hdulist)



        #mask = self._generateMask(hdulist_list[0])
        #for h in hdulist_list:
        #    h[0].mask = mask


        start = time.time()


        #reference_bitdepth = self._detectBitDepth(reference_hdulist[0].data)
        #reference_8bit = self._convert_16bit_to_8bit(reference_hdulist[0].data, 16, reference_bitdepth)
        #cv2.imwrite('original.png', reference_8bit, [cv2.IMWRITE_PNG_COMPRESSION, 9])


        reg_list = list()
        # add original target
        reg_list.append(reference_hdulist[0].data)

        ref_crop = self._crop(reference_hdulist[0].data)


        for hdulist in hdulist_list[1:]:
            # detection_sigma default = 5
            # max_control_points default = 50
            # min_area default = 5
            reg_start = time.time()


            try:
                ### Reusing the tranform does not appear to work
                #if isinstance(self.transform, type(None)):
                #    self.transform, (source_list, target_list) = astroalign.find_transform(
                #        hdulist[0],
                #        reference_hdulist[0],
                #        detection_sigma=5,
                #        max_control_points=50,
                #        min_area=10,
                #    )

                ### Find transform using a crop of the image
                hdu_crop = self._crop(hdulist[0].data)
                self.transform, (source_list, target_list) = astroalign.find_transform(
                    hdu_crop,
                    ref_crop,
                    detection_sigma=5,
                    max_control_points=50,
                    min_area=10,
                )

                logger.info(
                    'Registration Matches: %d, Rotation: %0.6f, Translation: (%0.6f, %0.6f), Scale: %0.6f',
                    len(target_list),
                    self.transform.rotation,
                    self.transform.translation[0], self.transform.translation[1],
                    self.transform.scale,
                )

                ### Apply transform
                reg_image, footprint = astroalign.apply_transform(
                    self.transform,
                    hdulist[0],
                    reference_hdulist[0],
                )


                ## Register full image
                #reg_image, footprint = astroalign.register(
                #    hdulist[0],
                #    reference_hdulist[0],
                #    detection_sigma=5,
                #    max_control_points=50,
                #    min_area=10,
                #    #propagate_mask=True,
                #)
            except astroalign.MaxIterError as e:
                logger.error('Error registering: %s', str(e))
                continue

            reg_elapsed_s = time.time() - reg_start
            logger.info('Image registered in %0.4f s', reg_elapsed_s)

            reg_list.append(reg_image)



        stacker = ImageStacker()
        stacker_method = getattr(stacker, self.method)

        stacked_img = stacker_method(reg_list, numpy.uint16)

        elapsed_s = time.time() - start
        logger.info('Images aligned in %0.4f s', elapsed_s)

        stacked_bitdepth = self._detectBitDepth(stacked_img)
        stacked_img_8bit = self._convert_16bit_to_8bit(stacked_img, 16, stacked_bitdepth)

        cv2.imwrite(output, stacked_img_8bit, [cv2.IMWRITE_PNG_COMPRESSION, 9])
        #cv2.imwrite(output, stacked_img_8bit, [cv2.IMWRITE_JPEG_QUALITY, 90])


    def _detectBitDepth(self, data):
        ### This will need some rework if cameras return signed int data
        max_val = numpy.amax(data)
        logger.info('Image max value: %d', int(max_val))

        # This method of detecting bit depth can cause the 16->8 bit conversion
        # to stretch too much.  This most commonly happens with very low gains
        # during the day when there are no hot pixels.  This can result in a
        # trippy effect
        if max_val > 32768:
            image_bit_depth = 16
        elif max_val > 16384:
            image_bit_depth = 15
        elif max_val > 8192:
            image_bit_depth = 14
        elif max_val > 4096:
            image_bit_depth = 13
        elif max_val > 2096:
            image_bit_depth = 12
        elif max_val > 1024:
            image_bit_depth = 11
        elif max_val > 512:
            image_bit_depth = 10
        elif max_val > 256:
            image_bit_depth = 9
        else:
            image_bit_depth = 8

        logger.info('Detected bit depth: %d', image_bit_depth)

        return image_bit_depth


    def _convert_16bit_to_8bit(self, data, image_bitpix, image_bit_depth):
        if image_bitpix == 8:
            return

        logger.info('Resampling image from %d to 8 bits', image_bitpix)

        #div_factor = int((2 ** image_bit_depth) / 255)
        #return (data / div_factor).astype(numpy.uint8)

        # shifting is 5x faster than division
        shift_factor = image_bit_depth - 8
        return numpy.right_shift(data, shift_factor).astype(numpy.uint8)


    def _crop(self, image):
        image_height, image_width = image.shape[:2]

        x1 = int((image_width / 3) - (image_width / 3))
        y1 = int((image_height / 3) - (image_height / 3))
        x2 = int((image_width / 3) + (image_width / 3))
        y2 = int((image_height / 3) + (image_height / 3))


        return image[
            y1:y2,
            x1:x2,
        ]


    def _generateMask(self, hdulist):
        logger.info('Generating mask')

        image_height, image_width = hdulist[0].data.shape[:2]

        # create a black background
        mask = numpy.zeros((image_height, image_width), dtype=numpy.uint8)

        x1 = int((image_width / 2) - (image_width / 3))
        y1 = int((image_height / 2) - (image_height / 3))
        x2 = int((image_width / 2) + (image_width / 3))
        y2 = int((image_height / 2) + (image_height / 3))

        # The white area is what we keep
        cv2.rectangle(
            img=mask,
            pt1=(x1, y1),
            pt2=(x2, y2),
            color=(255),  # mono
            thickness=cv2.FILLED,
        )


        return numpy.invert(mask.astype(bool))


class ImageStacker(object):

    def mean(self, *args, **kwargs):
        # alias for average
        return self.average(*args, **kwargs)


    def average(self, stack_data, numpy_type):
        mean_image = numpy.mean(stack_data, axis=0)
        return numpy.floor(mean_image).astype(numpy_type)  # no floats


    def maximum(self, stack_data, numpy_type):
        image_max = stack_data[0]  # start with first image

        # compare with remaining images
        for i in stack_data[1:]:
            image_max = numpy.maximum(image_max, i)

        return image_max

    def minimum(self, stack_data, numpy_type):
        image_min = stack_data[0]  # start with first image

        # compare with remaining images
        for i in stack_data[1:]:
            image_min = numpy.minimum(image_min, i)

        return image_min



if __name__ == "__main__":
    argparser = argparse.ArgumentParser()
    argparser.add_argument(
        'inputfiles',
        help='Input files',
        metavar='I',
        type=str,
        nargs='+'
    )
    argparser.add_argument(
        '--output',
        '-o',
        help='output',
        type=str,
        required=True,
    )
    argparser.add_argument(
        '--reference',
        '-r',
        help='reference',
        type=str,
        required=True,
    )
    argparser.add_argument(
        '--method',
        '-m',
        help='method',
        type=str,
        required=True,
        choices=(
            'average',
            'maximum',
            'minimum',
        )
    )


    args = argparser.parse_args()

    a = Align(args.method)
    a.main(args.output, args.reference, args.inputfiles)


