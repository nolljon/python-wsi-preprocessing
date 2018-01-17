# -------------------------------------------------------------
#
# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.
#
# -------------------------------------------------------------

import math
import multiprocessing
import numpy as np
import os
import wsi.filter as filter
import wsi.slide as slide
from wsi.slide import Time
import PIL
from PIL import ImageDraw, ImageFont
from enum import Enum

TISSUE_THRESHOLD_PERCENT = 80
TISSUE_LOW_THRESHOLD_PERCENT = 10

ROW_TILE_SIZE = 1024
COL_TILE_SIZE = 1024

# Currently only works well for tile sizes >= 4096
# 2048 works decently by 2x image scaling except for displaying very large images such as S001
# One possibility would be to break the image into multiple images and use an image map on the thumbnail to navigate
# to the different sections of the image
DISPLAY_TILE_LABELS = False

TILE_BORDER_SIZE = 2  # The size of the colored rectangular border around summary tiles.

THRESH_COLOR = (0, 255, 0)
BELOW_THRESH_COLOR = (255, 255, 0)
BELOW_LOWER_THRESH_COLOR = (255, 165, 0)
NO_TISSUE_COLOR = (255, 0, 0)


def get_num_tiles(rows, cols, row_tile_size, col_tile_size):
  """
  Obtain the number of vertical and horizontal tiles that an image can be divided into given a row tile size and
  a column tile size.

  Args:
    rows: Number of rows.
    cols: Number of columns.
    row_tile_size: Number of pixels in a tile row.
    col_tile_size: Number of pixels in a tile column.

  Returns:
    Tuple consisting of the number of vertical tiles and the number of horizontal tiles that the image can be divided
    into given the row tile size and the column tile size.
  """
  num_row_tiles = math.ceil(rows / row_tile_size)
  num_col_tiles = math.ceil(cols / col_tile_size)
  return num_row_tiles, num_col_tiles


def get_tile_indices(rows, cols, row_tile_size, col_tile_size):
  """
  Obtain a list of tile coordinates (starting row, ending row, starting column, ending column, row number, column number).

  Args:
    rows: Number of rows.
    cols: Number of columns.
    row_tile_size: Number of pixels in a tile row.
    col_tile_size: Number of pixels in a tile column.

  Returns:
    List of tuples representing tile coordinates consisting of starting row, ending row,
    starting column, ending column, row number, column number.
  """
  indices = list()
  num_row_tiles, num_col_tiles = get_num_tiles(rows, cols, row_tile_size, col_tile_size)
  for r in range(0, num_row_tiles):
    start_r = r * row_tile_size
    end_r = ((r + 1) * row_tile_size) if (r < num_row_tiles - 1) else rows
    for c in range(0, num_col_tiles):
      start_c = c * col_tile_size
      end_c = ((c + 1) * col_tile_size) if (c < num_col_tiles - 1) else cols
      indices.append((start_r, end_r, start_c, end_c, r + 1, c + 1))
  return indices


def create_summary_pil_img(np_img, title_area_height, row_tile_size, col_tile_size, num_row_tiles, num_col_tiles):
  """
  Create a PIL summary image including top title area and right side and bottom padding.

  Args:
    np_img: Image as a NumPy array.
    title_area_height: Height of the title area at the top of the summary image.
    row_tile_size: The tile size in rows.
    col_tile_size: The tile size in columns.
    num_row_tiles: The number of row tiles.
    num_col_tiles: The number of column tiles.

  Returns:
    Summary image as a PIL image. This image contains the image data specified by the np_img input and also has
    potentially a top title area and right side and bottom padding.
  """
  r = row_tile_size * num_row_tiles + title_area_height
  c = col_tile_size * num_col_tiles
  summary_img = np.zeros([r, c, np_img.shape[2]], dtype=np.uint8)
  # add gray edges so that tile text does not get cut off
  summary_img.fill(120)
  # color title area white
  summary_img[0:title_area_height, 0:summary_img.shape[1]].fill(255)
  summary_img[title_area_height:np_img.shape[0] + title_area_height, 0:np_img.shape[1]] = np_img
  summary = filter.np_to_pil(summary_img)
  return summary


def generate_tile_summary_images(tile_sum, slide_num, np_img, display=True, save=False, text_color=(255, 255, 255),
                                 text_size=16, font_path="/Library/Fonts/Arial Bold.ttf"):
  """
  Generate summary images/thumbnails showing a 'heatmap' representation of the tissue segmentation of all tiles.

  Args:
    slide_num: The slide number.
    np_img: Image as a NumPy array.
    tile_indices: List of tuples consisting of starting row, ending row, starting column, ending column, row number,
                  column number.
    row_tile_size: Number of pixels in a tile row.
    col_tile_size: Number of pixels in a tile column.
    display: If True, display tile summary to screen.
    save: If True, save tile summary image.
    text_color: Font color (default white).
    text_size: Font size.
    font_path: Path to the font to use.
  """
  z = 300  # height of area at top of summary slide
  rows = tile_sum.scaled_h
  cols = tile_sum.scaled_w
  row_tile_size = tile_sum.scaled_tile_h
  col_tile_size = tile_sum.scaled_tile_w
  num_row_tiles, num_col_tiles = get_num_tiles(rows, cols, row_tile_size, col_tile_size)
  summary = create_summary_pil_img(np_img, z, row_tile_size, col_tile_size, num_row_tiles, num_col_tiles)
  draw = ImageDraw.Draw(summary)

  original_img_path = slide.get_training_image_path(slide_num)
  orig_img = slide.open_image(original_img_path)
  np_orig = filter.pil_to_np_rgb(orig_img)
  summary_orig = create_summary_pil_img(np_orig, z, row_tile_size, col_tile_size, num_row_tiles, num_col_tiles)
  draw_orig = ImageDraw.Draw(summary_orig)

  for t in tile_sum.tiles:
    border_color = tile_border_color(t.tissue_percentage)
    tile_border(draw, t.r_s + z, t.r_e + z, t.c_s, t.c_e, border_color)
    tile_border(draw_orig, t.r_s + z, t.r_e + z, t.c_s, t.c_e, border_color)

  summary_txt = summary_text(tile_sum)

  summary_font = ImageFont.truetype("/Library/Fonts/Courier New Bold.ttf", size=24)
  draw.text((5, 5), summary_txt, (0, 0, 0), font=summary_font)
  draw_orig.text((5, 5), summary_txt, (0, 0, 0), font=summary_font)

  if DISPLAY_TILE_LABELS:
    # resize image if 2048 for text display on tiles
    if COL_TILE_SIZE == 2048:
      f = 2
      w, h = summary.size
      w = w * f
      h = h * f
      summary = summary.resize((w, h), PIL.Image.BILINEAR)
      draw = ImageDraw.Draw(summary)
    else:
      f = 1
    count = 0
    for t in tile_sum.tiles:
      count += 1
      label = "#%d\nR%d C%d\n%4.2f%%\n[%d,%d] x\n[%d,%d]\n%dx%d" % (
        count, t.r, t.c, t.tissue_percentage, t.c_s, t.r_s, t.c_e, t.r_e, t.c_e - t.c_s, t.r_e - t.r_s)
      font = ImageFont.truetype(font_path, size=text_size)
      draw.text(((t.c_s + 4) * f, (t.r_s + 4 + z) * f), label, (0, 0, 0), font=font)
      draw.text(((t.c_s + 3) * f, (t.r_s + 3 + z) * f), label, (0, 0, 0), font=font)
      draw.text(((t.c_s + 2) * f, (t.r_s + 2 + z) * f), label, text_color, font=font)

  if display:
    summary.show()
    summary_orig.show()
  if save:
    save_tile_summary_image(summary, slide_num)
    save_tile_summary_on_original_image(summary_orig, slide_num)


def generate_top_tile_images(tile_sum, slide_num, np_img, display=True, save=False, text_color=(255, 255, 255),
                             text_size=10, font_path="/Library/Fonts/Arial Bold.ttf"):
  """
  Generate summary images/thumbnails showing the top tissue segmentation tiles.

  Args:
    tile_sum: TileSummary object.
    slide_num: The slide number.
    np_img: Image as a NumPy array.
    display: If True, display top tiles to screen.
    save: If True, save top tiles images.
    text_color: Font color (default white).
    text_size: Font size.
    font_path: Path to the font to use.
  """
  z = 300  # height of area at top of summary slide
  rows = tile_sum.scaled_h
  cols = tile_sum.scaled_w
  row_tile_size = tile_sum.scaled_tile_h
  col_tile_size = tile_sum.scaled_tile_w
  num_row_tiles, num_col_tiles = get_num_tiles(rows, cols, row_tile_size, col_tile_size)
  summary = create_summary_pil_img(np_img, z, row_tile_size, col_tile_size, num_row_tiles, num_col_tiles)
  draw = ImageDraw.Draw(summary)

  original_img_path = slide.get_training_image_path(slide_num)
  orig_img = slide.open_image(original_img_path)
  np_orig = filter.pil_to_np_rgb(orig_img)
  summary_orig = create_summary_pil_img(np_orig, z, row_tile_size, col_tile_size, num_row_tiles, num_col_tiles)
  draw_orig = ImageDraw.Draw(summary_orig)

  top_tiles = tile_sum.top_tiles()

  for t in top_tiles:
    border_color = tile_border_color(t.tissue_percentage)
    tile_border(draw, t.r_s + z, t.r_e + z, t.c_s, t.c_e, border_color)
    tile_border(draw_orig, t.r_s + z, t.r_e + z, t.c_s, t.c_e, border_color)

  summary_txt = summary_text(tile_sum)

  summary_font = ImageFont.truetype("/Library/Fonts/Courier New Bold.ttf", size=24)
  draw.text((5, 5), summary_txt, (0, 0, 0), font=summary_font)
  draw_orig.text((5, 5), summary_txt, (0, 0, 0), font=summary_font)

  for t in top_tiles:
    label = "R%d\nC%d" % (t.r, t.c)
    font = ImageFont.truetype(font_path, size=text_size)
    # drop shadow behind text
    draw.text(((t.c_s + 3), (t.r_s + 3 + z)), label, (0, 0, 0), font=font)
    draw_orig.text(((t.c_s + 3), (t.r_s + 3 + z)), label, (0, 0, 0), font=font)

    draw.text(((t.c_s + 2), (t.r_s + 2 + z)), label, text_color, font=font)
    draw_orig.text(((t.c_s + 2), (t.r_s + 2 + z)), label, text_color, font=font)

  if display:
    summary.show()
    summary_orig.show()
  if save:
    save_top_tiles_image(summary, slide_num)
    save_top_tiles_on_original_image(summary_orig, slide_num)


def tile_border_color(tissue_percentage):
  """
  Obtain the corresponding tile border color for a particular tile tissue percentage.

  Args:
    tissue_percentage: The tile tissue percentage

  Returns:
    The tile border color corresponding to the tile tissue percentage.
  """
  if tissue_percentage >= TISSUE_THRESHOLD_PERCENT:
    border_color = THRESH_COLOR
  elif (tissue_percentage >= TISSUE_LOW_THRESHOLD_PERCENT) and (tissue_percentage < TISSUE_THRESHOLD_PERCENT):
    border_color = BELOW_THRESH_COLOR
  elif (tissue_percentage > 0) and (tissue_percentage < TISSUE_LOW_THRESHOLD_PERCENT):
    border_color = BELOW_LOWER_THRESH_COLOR
  else:
    border_color = NO_TISSUE_COLOR
  return border_color


def summary_text(tile_summary):
  return "Slide #%03d Tissue Segmentation Summary:\n" % tile_summary.slide_num + \
         "Original Dimensions: %dx%d\n" % (tile_summary.orig_w, tile_summary.orig_h) + \
         "Original Tile Size: %dx%d\n" % (tile_summary.orig_tile_w, tile_summary.orig_tile_h) + \
         "Scale Factor: 1/%dx\n" % tile_summary.scale_factor + \
         "Scaled Dimensions: %dx%d\n" % (tile_summary.scaled_w, tile_summary.scaled_h) + \
         "Scaled Tile Size: %dx%d\n" % (tile_summary.scaled_tile_w, tile_summary.scaled_tile_w) + \
         "Total Mask: %3.2f%%, Total Tissue: %3.2f%%\n" % (
           tile_summary.mask_percentage(), tile_summary.tissue_percentage) + \
         "Tiles: %dx%d = %d\n" % (tile_summary.num_col_tiles, tile_summary.num_row_tiles, tile_summary.count) + \
         " %5d (%5.2f%%) tiles >=%d%% tissue\n" % (
           tile_summary.high, tile_summary.high / tile_summary.count * 100, TISSUE_THRESHOLD_PERCENT) + \
         " %5d (%5.2f%%) tiles >=%d%% and <%d%% tissue\n" % (
           tile_summary.medium, tile_summary.medium / tile_summary.count * 100, TISSUE_LOW_THRESHOLD_PERCENT,
           TISSUE_THRESHOLD_PERCENT) + \
         " %5d (%5.2f%%) tiles >0%% and <%d%% tissue\n" % (
           tile_summary.low, tile_summary.low / tile_summary.count * 100, TISSUE_LOW_THRESHOLD_PERCENT) + \
         " %5d (%5.2f%%) tiles =0%% tissue" % (tile_summary.none, tile_summary.none / tile_summary.count * 100)


def tile_border(draw, r_s, r_e, c_s, c_e, color):
  """
  Draw a border around a tile with width TILE_BORDER_SIZE.

  Args:
    draw: Draw object for drawing on PIL image.
    r_s: Row starting pixel.
    r_e: Row ending pixel.
    c_s: Column starting pixel.
    c_e: Column ending pixel.
    color: Color of the border.
  """
  for x in range(0, TILE_BORDER_SIZE):
    draw.rectangle([(c_s + x, r_s + x), (c_e - 1 - x, r_e - 1 - x)], outline=color)


def save_tile_summary_image(pil_img, slide_num):
  """
  Save a tile summary image and thumbnail to the file system.

  Args:
    pil_img: Image as a PIL Image.
    slide_num: The slide number.
  """
  t = Time()
  filepath = slide.get_tile_summary_image_path(slide_num)
  pil_img.save(filepath)
  print("%-20s | Time: %-14s  Name: %s" % ("Save Tile Summary Image", str(t.elapsed()), filepath))

  t = Time()
  thumbnail_filepath = slide.get_tile_summary_thumbnail_path(slide_num)
  slide.save_thumbnail(pil_img, slide.THUMBNAIL_SIZE, thumbnail_filepath)
  print("%-20s | Time: %-14s  Name: %s" % ("Save Tile Summary Thumbnail", str(t.elapsed()), thumbnail_filepath))


def save_top_tiles_image(pil_img, slide_num):
  """
  Save a top tiles image and thumbnail to the file system.

  Args:
    pil_img: Image as a PIL Image.
    slide_num: The slide number.
  """
  t = Time()
  filepath = slide.get_top_tiles_image_path(slide_num)
  pil_img.save(filepath)
  print("%-20s | Time: %-14s  Name: %s" % ("Save Top Tiles Image", str(t.elapsed()), filepath))

  t = Time()
  thumbnail_filepath = slide.get_top_tiles_thumbnail_path(slide_num)
  slide.save_thumbnail(pil_img, slide.THUMBNAIL_SIZE, thumbnail_filepath)
  print("%-20s | Time: %-14s  Name: %s" % ("Save Top Tiles Thumbnail", str(t.elapsed()), thumbnail_filepath))


def save_tile_summary_on_original_image(pil_img, slide_num):
  """
  Save a tile summary on original image and thumbnail to the file system.

  Args:
    pil_img: Image as a PIL Image.
    slide_num: The slide number.
  """
  t = Time()
  filepath = slide.get_tile_summary_on_original_image_path(slide_num)
  pil_img.save(filepath)
  print("%-20s | Time: %-14s  Name: %s" % ("Save Tile Summary on Original Image", str(t.elapsed()), filepath))

  t = Time()
  thumbnail_filepath = slide.get_tile_summary_on_original_thumbnail_path(slide_num)
  slide.save_thumbnail(pil_img, slide.THUMBNAIL_SIZE, thumbnail_filepath)
  print(
    "%-20s | Time: %-14s  Name: %s" % ("Save Tile Summary on Original Thumbnail", str(t.elapsed()), thumbnail_filepath))


def save_top_tiles_on_original_image(pil_img, slide_num):
  """
  Save a top tiles on original image and thumbnail to the file system.

  Args:
    pil_img: Image as a PIL Image.
    slide_num: The slide number.
  """
  t = Time()
  filepath = slide.get_top_tiles_on_original_image_path(slide_num)
  pil_img.save(filepath)
  print("%-20s | Time: %-14s  Name: %s" % ("Save Top Tiles on Original Image", str(t.elapsed()), filepath))

  t = Time()
  thumbnail_filepath = slide.get_top_tiles_on_original_thumbnail_path(slide_num)
  slide.save_thumbnail(pil_img, slide.THUMBNAIL_SIZE, thumbnail_filepath)
  print(
    "%-20s | Time: %-14s  Name: %s" % ("Save Top Tiles on Original Thumbnail", str(t.elapsed()), thumbnail_filepath))


def summary(slide_num, display=True, save=False, save_data=True):
  """
  Display and/or save a summary image of tiles.

  Args:
    slide_num: The slide number.
    display: If True, display tile summary to screen.
    save: If True, save tile summary image.
    save_data: If True, save tile data to csv file.

  """
  img_path = slide.get_filter_image_result(slide_num)
  img = slide.open_image(img_path)
  np_img = filter.pil_to_np_rgb(img)

  tile_sum = compute_tile_summary(slide_num, np_img)
  if save_data:
    save_tile_data(tile_sum)
  generate_tile_summary_images(tile_sum, slide_num, np_img, display=display, save=save)
  generate_top_tile_images(tile_sum, slide_num, np_img, display=display, save=save)


def save_tile_data(tile_summary):
  """
  Save tile data to csv file.

  Args
    tile_summary: TimeSummary object.
  """

  time = Time()

  csv = summary_text(tile_summary)

  csv += "\n\n\nTile Num,Row,Column,Tissue %,Tissue Quantity,Col Start,Row Start,Col End,Row End,Col Size,Row Size," + \
         "Original Col Start,Original Row Start,Original Col End,Original Row End,Original Col Size,Original Row Size\n"

  for t in tile_summary.tiles:
    line = "%d,%d,%d,%4.2f,%s,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n" % (
      t.tile_num, t.r, t.c, t.tissue_percentage, t.tissue_quantity().name, t.c_s, t.r_s, t.c_e, t.r_e, t.c_e - t.c_s,
      t.r_e - t.r_s, t.o_c_s, t.o_r_s, t.o_c_e, t.o_r_e, t.o_c_e - t.o_c_s, t.o_r_e - t.o_r_s)
    csv += line

  data_path = slide.get_tile_data_path(tile_summary.slide_num)
  csv_file = open(data_path, "w")
  csv_file.write(csv)
  csv_file.close()

  print("%-20s | Time: %-14s  Name: %s" % ("Save Tile Data", str(time.elapsed()), data_path))


def save_display_tile(slide_number, tile_info, save=False, display=True):
  """
  Save and/or display a tile image.

  Args:
    slide_number: The slide number.
  """
  slide_filepath = slide.get_training_slide_path(slide_number)
  s = slide.open_slide(slide_filepath)
  t = tile_info
  x, y = t.o_c_s, t.o_r_s
  w, h = t.o_c_e - t.o_c_s, t.o_r_e - t.o_r_s
  tile_region = s.read_region((x, y), 0, (w, h))
  # RGBA to RGB
  tile_region = tile_region.convert("RGB")

  if save:
    img_path = slide.get_tile_image_path(slide_number, t)
    print("Saving tile to: " + img_path)
    dir = os.path.dirname(img_path)
    if not os.path.exists(dir):
      os.makedirs(dir)
    tile_region.save(img_path)

  if display:
    tile_region.show()


def compute_tile_summary(slide_num, np_img=None):
  """
  Generate a tile summary consisting of summary statistics and also information about each tile such as tissue
  percentage and coordinates.

  Args:
    slide_num: The slide number.
    np_img: Image as a NumPy array.

  Returns:
    TileSummary object which includes a list of TileInfo objects containing information about each tile.
  """
  img_path = slide.get_filter_image_result(slide_num)
  o_w, o_h, w, h = slide.parse_dimensions_from_image_filename(img_path)

  if np_img is None:
    img = slide.open_image(img_path)
    np_img = filter.pil_to_np_rgb(img)

  row_tile_size = round(ROW_TILE_SIZE / slide.SCALE_FACTOR)  # use round?
  col_tile_size = round(COL_TILE_SIZE / slide.SCALE_FACTOR)  # use round?

  num_row_tiles, num_col_tiles = get_num_tiles(h, w, row_tile_size, col_tile_size)

  tile_sum = TileSummary(slide_num=slide_num,
                         orig_w=o_w,
                         orig_h=o_h,
                         orig_tile_w=COL_TILE_SIZE,
                         orig_tile_h=ROW_TILE_SIZE,
                         scaled_w=w,
                         scaled_h=h,
                         scaled_tile_w=col_tile_size,
                         scaled_tile_h=row_tile_size,
                         tissue_percentage=filter.tissue_percent(np_img),
                         num_col_tiles=num_col_tiles,
                         num_row_tiles=num_row_tiles)

  count = 0
  high = 0
  medium = 0
  low = 0
  none = 0
  tile_indices = get_tile_indices(h, w, row_tile_size, col_tile_size)
  for t in tile_indices:
    count += 1  # tile_num
    r_s, r_e, c_s, c_e, r, c = t
    np_tile = np_img[r_s:r_e, c_s:c_e]
    t_p = filter.tissue_percent(np_tile)
    o_c_s, o_r_s = slide.small_to_large_mapping((c_s, r_s), (o_w, o_h))
    o_c_e, o_r_e = slide.small_to_large_mapping((c_e, r_e), (o_w, o_h))

    # pixel adjustment in case tile dimension too large (for example, 1025 instead of 1024)
    if (o_c_e - o_c_s) > COL_TILE_SIZE:
      o_c_e -= 1
    if (o_r_e - o_r_s) > ROW_TILE_SIZE:
      o_r_e -= 1

    tile_info = TileInfo(count, r, c, r_s, r_e, c_s, c_e, o_r_s, o_r_e, o_c_s, o_c_e, t_p)
    tile_sum.tiles.append(tile_info)

    amount = tissue_quantity(t_p)
    if amount == TissueQuantity.HIGH:
      high += 1
    elif amount == TissueQuantity.MEDIUM:
      medium += 1
    elif amount == TissueQuantity.LOW:
      low += 1
    elif amount == TissueQuantity.NONE:
      none += 1

  tile_sum.count = count
  tile_sum.high = high
  tile_sum.medium = medium
  tile_sum.low = low
  tile_sum.none = none

  return tile_sum


def tissue_quantity(tissue_percentage):
  """
  Obtain TissueQuantity enum member (HIGH, MEDIUM, LOW, or NONE) for corresponding tissue percentage.

  Args:
    tissue_percentage: The tile tissue percentage.

  Returns:
    TissueQuantity enum member (HIGH, MEDIUM, LOW, or NONE).
  """
  if tissue_percentage >= TISSUE_THRESHOLD_PERCENT:
    return TissueQuantity.HIGH
  elif (tissue_percentage >= TISSUE_LOW_THRESHOLD_PERCENT) and (tissue_percentage < TISSUE_THRESHOLD_PERCENT):
    return TissueQuantity.MEDIUM
  elif (tissue_percentage > 0) and (tissue_percentage < TISSUE_LOW_THRESHOLD_PERCENT):
    return TissueQuantity.LOW
  else:
    return TissueQuantity.NONE


def image_list_to_tile_summaries(image_num_list, display=False, save=True, save_data=True):
  """
  Generate tile summaries for a list of images.

  Args:
    image_num_list: List of image numbers.
    display: If True, display tile summary images to screen.
    save: If True, save tile summary images.
    save_data: If True, save tile data to csv file.
  """
  for slide_num in image_num_list:
    summary(slide_num, display, save, save_data)
  return image_num_list


def image_range_to_tile_summaries(start_ind, end_ind, display=False, save=True, save_data=True):
  """
  Generate tile summaries for a range of images.

  Args:
    start_ind: Starting index (inclusive).
    end_ind: Ending index (inclusive).
    display: If True, display tile summary images to screen.
    save: If True, save tile summary images.
    save_data: If True, save tile data to csv file.
  """
  image_num_list = list()
  for slide_num in range(start_ind, end_ind + 1):
    summary(slide_num, display, save, save_data)
    image_num_list.append(slide_num)
  return image_num_list


def singleprocess_images_to_tile_summaries(display=False, save=True, save_data=True, html=True, image_num_list=None):
  """
  Generate tile summaries for training images and optionally save/and or display the tile summaries.

  Args:
    display: If True, display tile summary images to screen.
    save: If True, save tile summary images.
    save_data: If True, save tile data to csv file.
    html: If True, generate HTML page to display tiled images
    image_num_list: Optionally specify a list of image slide numbers.
  """
  t = Time()
  print("Generating tile summaries\n")

  if image_num_list is not None:
    image_list_to_tile_summaries(image_num_list, display, save, save_data)
  else:
    num_training_slides = slide.get_num_training_slides()
    image_num_list = image_range_to_tile_summaries(1, num_training_slides, display, save, save_data)

  print("Time to generate tile summaries: %s\n" % str(t.elapsed()))

  if html:
    generate_tiled_html_result(image_num_list, save_data)


def multiprocess_images_to_tile_summaries(display=False, save=True, save_data=True, html=True, image_num_list=None):
  """
  Generate tile summaries for all training images using multiple processes (one process per core).

  Args:
    display: If True, display images to screen (multiprocessed display not recommended).
    save: If True, save images.
    save_data: If True, save tile data to csv file.
    html: If True, generate HTML page to display tiled images.
    image_num_list: Optionally specify a list of image slide numbers.
  """
  timer = Time()
  print("Generating tile summaries (multiprocess)\n")

  if save and not os.path.exists(slide.TILE_SUMMARY_DIR):
    os.makedirs(slide.TILE_SUMMARY_DIR)

  # how many processes to use
  num_processes = multiprocessing.cpu_count()
  pool = multiprocessing.Pool(num_processes)

  if image_num_list is not None:
    num_train_images = len(image_num_list)
  else:
    num_train_images = slide.get_num_training_slides()
  if num_processes > num_train_images:
    num_processes = num_train_images
  images_per_process = num_train_images / num_processes

  print("Number of processes: " + str(num_processes))
  print("Number of training images: " + str(num_train_images))

  tasks = []
  for num_process in range(1, num_processes + 1):
    start_index = (num_process - 1) * images_per_process + 1
    end_index = num_process * images_per_process
    start_index = int(start_index)
    end_index = int(end_index)
    if image_num_list is not None:
      sublist = image_num_list[start_index - 1:end_index]
      tasks.append((sublist, display, save, save_data))
      print("Task #" + str(num_process) + ": Process slides " + str(sublist))
    else:
      tasks.append((start_index, end_index, display, save, save_data))
      if start_index == end_index:
        print("Task #" + str(num_process) + ": Process slide " + str(start_index))
      else:
        print("Task #" + str(num_process) + ": Process slides " + str(start_index) + " to " + str(end_index))

  # start tasks
  results = []
  for t in tasks:
    if image_num_list is not None:
      results.append(pool.apply_async(image_list_to_tile_summaries, t))
    else:
      results.append(pool.apply_async(image_range_to_tile_summaries, t))

  slide_nums = list()
  for result in results:
    image_nums = result.get()
    slide_nums.extend(image_nums)
    print("Done tiling slides: %s" % image_nums)

  if html:
    generate_tiled_html_result(slide_nums, save_data)

  print("Time to generate tile previews (multiprocess): %s\n" % str(timer.elapsed()))


def image_row(slide_num, data_link):
  """
  Generate HTML for viewing a tiled image.

  Args:
    slide_num: The slide number.
    data_link: If True, add link to tile data csv file.

  Returns:
    HTML table row for viewing a tiled image.
  """
  orig_img = slide.get_training_image_path(slide_num)
  orig_thumb = slide.get_training_thumbnail_path(slide_num)
  filt_img = slide.get_filter_image_result(slide_num)
  filt_thumb = slide.get_filter_thumbnail_result(slide_num)
  sum_img = slide.get_tile_summary_image_path(slide_num)
  sum_thumb = slide.get_tile_summary_thumbnail_path(slide_num)
  osum_img = slide.get_tile_summary_on_original_image_path(slide_num)
  osum_thumb = slide.get_tile_summary_on_original_thumbnail_path(slide_num)
  top_img = slide.get_top_tiles_image_path(slide_num)
  top_thumb = slide.get_top_tiles_thumbnail_path(slide_num)
  otop_img = slide.get_top_tiles_on_original_image_path(slide_num)
  otop_thumb = slide.get_top_tiles_on_original_thumbnail_path(slide_num)
  html = "    <tr>\n" + \
         "      <td>\n" + \
         "        <a target=\"_blank\" href=\"%s\">S%03d Original<br/>\n" % (orig_img, slide_num) + \
         "          <img class=\"lazyload\" src=\"%s\" data-src=\"%s\" />\n" % (filter.b64_img(), orig_thumb) + \
         "        </a>\n" + \
         "      </td>\n" + \
         "      <td>\n" + \
         "        <a target=\"_blank\" href=\"%s\">S%03d Filtered<br/>\n" % (filt_img, slide_num) + \
         "          <img class=\"lazyload\" src=\"%s\" data-src=\"%s\" />\n" % (filter.b64_img(), filt_thumb) + \
         "        </a>\n" + \
         "      </td>\n"
  if data_link:
    data_file = slide.get_tile_data_path(slide_num)
    html += "      <td>\n" + \
            "        <a target=\"_blank\" href=\"%s\">S%03d Tiled</a> " % (sum_img, slide_num) + \
            "        (<a target=\"_blank\" href=\"%s\">Data</a>)<br/>\n" % data_file + \
            "        <a target=\"_blank\" href=\"%s\">" % sum_img + \
            "          <img class=\"lazyload\" src=\"%s\" data-src=\"%s\" />\n" % (filter.b64_img(), sum_thumb) + \
            "        </a>\n" + \
            "      </td>\n"
  else:
    html += "      <td>\n" + \
            "        <a target=\"_blank\" href=\"%s\">S%03d Tiled<br/>\n" % (sum_img, slide_num) + \
            "          <img class=\"lazyload\" src=\"%s\" data-src=\"%s\" />\n" % (filter.b64_img(), sum_thumb) + \
            "        </a>\n" + \
            "      </td>\n"

  html += "      <td>\n" + \
          "        <a target=\"_blank\" href=\"%s\">S%03d Original Tiled<br/>\n" % (osum_img, slide_num) + \
          "          <img class=\"lazyload\" src=\"%s\" data-src=\"%s\" />\n" % (filter.b64_img(), osum_thumb) + \
          "        </a>\n" + \
          "      </td>\n"

  html += "      <td>\n" + \
          "        <a target=\"_blank\" href=\"%s\">S%03d Top Tiles<br/>\n" % (top_img, slide_num) + \
          "          <img class=\"lazyload\" src=\"%s\" data-src=\"%s\" />\n" % (filter.b64_img(), top_thumb) + \
          "        </a>\n" + \
          "      </td>\n"

  html += "      <td>\n" + \
          "        <a target=\"_blank\" href=\"%s\">S%03d Original Top Tiles<br/>\n" % (otop_img, slide_num) + \
          "          <img class=\"lazyload\" src=\"%s\" data-src=\"%s\" />\n" % (filter.b64_img(), otop_thumb) + \
          "        </a>\n" + \
          "      </td>\n"

  html += "    </tr>\n"
  return html


def generate_tiled_html_result(slide_nums, data_link):
  """
  Generate HTML to view the tiled images.

  Args:
    slide_nums: List of slide numbers.
    data_link: If True, add link to tile data csv file.
  """
  slide_nums = sorted(slide_nums)
  if not slide.TILE_SUMMARY_PAGINATE:
    html = ""
    html += filter.html_header("Tiled Images")

    html += "  <table>\n"
    for slide_num in slide_nums:
      html += image_row(slide_num, data_link)
    html += "  </table>\n"

    html += filter.html_footer()
    text_file = open(slide.TILE_SUMMARY_HTML_DIR + os.sep + "tiles.html", "w")
    text_file.write(html)
    text_file.close()
  else:
    total_len = len(slide_nums)
    page_size = slide.TILE_SUMMARY_PAGINATION_SIZE
    num_pages = math.ceil(total_len / page_size)
    for page_num in range(1, num_pages + 1):
      start_index = (page_num - 1) * page_size
      end_index = (page_num * page_size) if (page_num < num_pages) else total_len
      page_slide_nums = slide_nums[start_index:end_index]

      html = ""
      html += filter.html_header("Tiled Images, Page %d" % page_num)

      html += "  <div style=\"font-size: 20px\">"
      if page_num > 1:
        if page_num == 2:
          html += "<a href=\"tiles.html\">&lt;</a> "
        else:
          html += "<a href=\"tiles-%d.html\">&lt;</a> " % (page_num - 1)
      html += "Page %d" % page_num
      if page_num < num_pages:
        html += " <a href=\"tiles-%d.html\">&gt;</a> " % (page_num + 1)
      html += "</div>\n"

      html += "  <table>\n"
      for slide_num in page_slide_nums:
        html += image_row(slide_num, data_link)
      html += "  </table>\n"

      html += filter.html_footer()
      if page_num == 1:
        text_file = open(slide.TILE_SUMMARY_HTML_DIR + os.sep + "tiles.html", "w")
      else:
        text_file = open(slide.TILE_SUMMARY_HTML_DIR + os.sep + "tiles-%d.html" % page_num, "w")
      text_file.write(html)
      text_file.close()


class TileSummary:
  """
  Class for tile summary information.
  """

  slide_num = None
  orig_w = None
  orig_h = None
  orig_tile_w = None
  orig_tile_h = None
  scale_factor = slide.SCALE_FACTOR
  scaled_w = None
  scaled_h = None
  scaled_tile_w = None
  scaled_tile_h = None
  mask_percentage = None
  num_row_tiles = None
  num_col_tiles = None

  count = 0
  high = 0
  medium = 0
  low = 0
  none = 0

  def __init__(self, slide_num, orig_w, orig_h, orig_tile_w, orig_tile_h, scaled_w, scaled_h, scaled_tile_w,
               scaled_tile_h, tissue_percentage, num_col_tiles, num_row_tiles):
    self.slide_num = slide_num
    self.orig_w = orig_w
    self.orig_h = orig_h
    self.orig_tile_w = orig_tile_w
    self.orig_tile_h = orig_tile_h
    self.scaled_w = scaled_w
    self.scaled_h = scaled_h
    self.scaled_tile_w = scaled_tile_w
    self.scaled_tile_h = scaled_tile_h
    self.tissue_percentage = tissue_percentage
    self.num_col_tiles = num_col_tiles
    self.num_row_tiles = num_row_tiles
    self.tiles = []

  def __str__(self):
    return summary_text(self)

  def mask_percentage(self):
    return 100 - self.tissue_percentage

  def num_tiles(self):
    return self.num_row_tiles * self.num_col_tiles

  def tiles_by_tissue_percentage(self):
    sorted_list = sorted(self.tiles, key=lambda t: t.tissue_percentage, reverse=True)
    return sorted_list

  def top_tiles(self):
    sorted_tiles = self.tiles_by_tissue_percentage()
    top_tiles = sorted_tiles[:100]
    return top_tiles


class TileInfo:
  """
  Class for information about a tile.
  """
  tile_num = None
  r = None
  c = None
  r_s = None
  r_e = None
  c_s = None
  c_e = None
  o_r_s = None
  o_r_e = None
  o_c_s = None
  o_c_e = None
  tissue_percentage = None

  def __init__(self, tile_num, r, c, r_s, r_e, c_s, c_e, o_r_s, o_r_e, o_c_s, o_c_e, t_p):
    self.tile_num = tile_num
    self.r = r
    self.c = c
    self.r_s = r_s
    self.r_e = r_e
    self.c_s = c_s
    self.c_e = c_e
    self.o_r_s = o_r_s
    self.o_r_e = o_r_e
    self.o_c_s = o_c_s
    self.o_c_e = o_c_e
    self.tissue_percentage = t_p

  def __str__(self):
    return "[Tile #%d, Row #%d, Column #%d, Tissue %4.2f%%]" % (self.tile_num, self.r, self.c, self.tissue_percentage)

  def __repr__(self):
    return "\n" + self.__str__()

  def mask_percentage(self):
    return 100 - self.tissue_percentage

  def tissue_quantity(self):
    return tissue_quantity(self.tissue_percentage)


class TissueQuantity(Enum):
  NONE = 0
  LOW = 1
  MEDIUM = 2
  HIGH = 3


# summary(1, save=True)
# summary(26, save=True)
# image_list_to_tile_summaries([1, 2, 3, 4], display=True)
# image_range_to_tile_summaries(1, 50)
# singleprocess_images_to_tile_summaries(image_num_list=[1,10,14], display=True, save=False)
# multiprocess_images_to_tile_summaries(image_num_list=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12], display=False)
# singleprocess_images_to_tile_summaries()
# multiprocess_images_to_tile_summaries(image_num_list=[1, 2, 3, 4, 5], save=True, save_data=True, display=False)
# multiprocess_images_to_tile_summaries(save=False, display=False, html=True)
# multiprocess_images_to_tile_summaries()
# summary(2, display=True, save=False)
# generate_tiled_html_result(slide_nums=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
# generate_tiled_html_result(slide_nums=[10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
tile_sum = compute_tile_summary(4)
top = tile_sum.top_tiles()
save_display_tile(4, top[0], save=True)
