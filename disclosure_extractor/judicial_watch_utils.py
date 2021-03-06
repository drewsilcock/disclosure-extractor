import json
import tempfile
from itertools import groupby

import cv2
import numpy as np
import pandas as pd
from PIL import Image
from PyPDF2 import PdfFileReader
from pdf2image import convert_from_path

from disclosure_extractor.data_processing import ocr_slice, clean_stock_names
from disclosure_extractor.image_processing import (
    find_redactions,
    load_template,
)


def box_extraction(page):

    open_cv_image = np.array(page)
    img = open_cv_image[:, :, ::-1].copy()
    img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    (thresh, img_bin) = cv2.threshold(
        img, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )
    img_bin = 255 - img_bin

    # Defining a kernel length
    kernel_length = np.array(img).shape[1] // 200

    # A verticle kernel of (1 X kernel_length), which will detect all the verticle lines from the image.
    verticle_kernel = cv2.getStructuringElement(
        cv2.MORPH_RECT, (1, kernel_length)
    )

    # A horizontal kernel of (kernel_length X 1), which will help to detect all the horizontal line from the image.
    hori_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_length, 1))

    # A kernel of (3 X 3) ones.
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    # Morphological operation to detect verticle lines from an image
    img_temp1 = cv2.erode(img_bin, verticle_kernel, iterations=3)
    verticle_lines_img = cv2.dilate(img_temp1, verticle_kernel, iterations=3)

    # Morphological operation to detect horizontal lines from an image
    img_temp2 = cv2.erode(img_bin, hori_kernel, iterations=3)
    horizontal_lines_img = cv2.dilate(img_temp2, hori_kernel, iterations=3)

    # Weighting parameters, this will decide the quantity of an image to be added to make a new image.
    alpha = 0.5
    beta = 1.0 - alpha

    # This function helps to add two image with specific weight parameter to get a third image as summation of two image.
    img_final_bin = cv2.addWeighted(
        verticle_lines_img, alpha, horizontal_lines_img, beta, 0.0
    )
    img_final_bin = cv2.erode(~img_final_bin, kernel, iterations=2)
    (thresh, img_final_bin) = cv2.threshold(
        img_final_bin, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
    )

    mode = cv2.RETR_CCOMP
    method = cv2.CHAIN_APPROX_SIMPLE
    contours, hierarchy = cv2.findContours(img_final_bin, mode, method)

    return contours, hierarchy, img_final_bin


def get_investment_pages(pdf_bytes):
    """"""

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(pdf_bytes)

        pg_count = PdfFileReader(tmp.name).numPages
        pages = convert_from_path(tmp.name)
        if pg_count == "6":
            return pages[:3], pages[3:-2], pages[-2]
        cv_image = np.array(pages[3])
        avg_color_per_row = np.average(cv_image, axis=0)
        avg_color = np.average(avg_color_per_row, axis=0)
        if avg_color[0] > 245:
            return pages[:4], pages[4:-2], pages[-2]
        else:
            return pages[:3], pages[3:-2], pages[-2]


def get_text_fields(non_investment_pages):
    pg_num = 0
    s1 = []
    for page in non_investment_pages:
        page = page.resize((1653, 2180))
        contours, hierarchy, _ = box_extraction(page)
        i = 0
        while i < len(contours):
            x, y, w, h = cv2.boundingRect(contours[i])
            if w / h > 7 and 1200 > w > 175:
                rect = (x, y, w, h, pg_num, range(y, y + h))
                s1.append(rect)
            i += 1
        pg_num += 1
    return s1


def identify_sections(s1):
    results = load_template()
    df2 = pd.DataFrame(
        {
            "x": [x[0] for x in s1],
            "y": [x[1] for x in s1],
            "w": [x[2] for x in s1],
            "h": [x[3] for x in s1],
            "top": [x[1] + 10 for x in s1],
            "page": [x[4] for x in s1],
        }
    )

    df2 = df2.sort_values(["page", "y", "top"])
    df2["group"] = (
        (
            df2.top.rolling(window=2, min_periods=1).min()
            - df2.y.rolling(window=2, min_periods=1).max()
        )
        < 0
    ).cumsum()
    ndf2 = df2.groupby("group").filter(lambda x: len(x) > 1)
    other_sections = json.loads(ndf2.to_json(orient="table"))
    other_groups = groupby(
        other_sections["data"],
        lambda content: content["group"],
    )
    section = None
    sect_name = None
    last_top = None

    row_index = 0
    for grouping in other_groups:
        col_indx = 0
        groups = list(grouping[1])
        ordered_grp = sorted(groups, key=lambda x: x["x"])
        if section is None:
            section = 1
            sect_name = "Positions"
            # print("\n Section #", section, "\n")
        elif section == 1 and ordered_grp[0]["w"] < 500:
            section = 2
            sect_name = "Agreements"
            # print("\n Section #", section, "\n")
        elif section == 2 and len(ordered_grp) == 3:
            section = 3
            sect_name = "Non-Investment Income"
            # print("\n Section #", section, "\n")
        elif section == 3 and len(ordered_grp) == 2:
            section = 4
            sect_name = "Non Investment Income Spouse"
            # print("\n Section #", section, "\n")
        elif len(ordered_grp) == 5 and section != 5:
            section = 5
            sect_name = "Reimbursements"
            # print("\n Section #", section, "\n")
        elif section == 5 and len(ordered_grp) == 3 and section != 6:
            section = 6
            sect_name = "Gifts"
            # print("\n Section #", section, "\n")
        elif section == 6 and (abs(last_top - ordered_grp[0]["top"]) > 200):
            section = 7
            sect_name = "Liabilities"
            # print("\n Section #", section, "\n")
        last_top = ordered_grp[0]["top"]
        if ordered_grp[0]["x"] > 200:
            continue

        if results["sections"][sect_name]["rows"] == {}:
            row_index = 0
        results["sections"][sect_name]["rows"][row_index] = {}
        for group in sorted(groups, key=lambda x: x["x"]):
            group["coords"] = (
                group["x"],
                group["y"] - 60,
                (group["x"] + group["w"]),
                (group["y"] + group["h"]),
            )
            # print(results["sections"][sect]["columns"], col_indx)
            try:
                column = results["sections"][sect_name]["columns"][col_indx]

                results["sections"][sect_name]["rows"][row_index][
                    column
                ] = group
                results["sections"][sect_name]["empty"] = False
                results["sections"][sect_name]["rows"][row_index][column][
                    "section"
                ] = sect_name
                col_indx += 1
            except:
                pass
        row_index += 1
    return results


def extract_section_I_to_VI(results, pages):

    for k, v in results["sections"].items():
        for x, row in v["rows"].items():
            ocr_key = 1
            for y, column in row.items():
                old_page = pages[column["page"]]
                page = old_page.resize((1653, 2180))

                crop = page.crop(column["coords"])
                if column["section"] == "Liabilities":
                    ocr_key += 1
                    if ocr_key == 4:
                        text = ocr_slice(crop, ocr_key).strip()
                    else:
                        text = ocr_slice(crop, 1).strip()
                else:
                    text = ocr_slice(crop, ocr_key).strip()
                results["sections"][k]["rows"][x][y] = {}
                results["sections"][k]["rows"][x][y]["text"] = text
                results["sections"][k]["rows"][x][y][
                    "is_redacted"
                ] = find_redactions(crop)
    return results


def extract_section_VII(results, investment_pages):
    """"""
    k = "Investments and Trusts"
    columns = results["sections"]["Investments and Trusts"]["columns"]
    row_count = 0
    for page in investment_pages:
        data = extract_page(page)
        for row in data:
            i = 0
            row_index = str(row_count)
            results["sections"]["Investments and Trusts"]["rows"][
                row_index
            ] = {}
            for item in row:
                column = columns[i]
                i += 1
                color_coverted = cv2.cvtColor(item, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(color_coverted)
                t = ocr_slice(pil_image, i)

                results["sections"][k]["rows"][row_index][column] = {
                    "text": clean_stock_names(t),
                    "is_redacted": find_redactions(pil_image),
                }

            row_count += 1

    return results


def process_addendum(addendum_page):
    """"""
    width, height = addendum_page.size
    slice = addendum_page.crop(
        (
            0,
            height * 0.15,
            width,
            height * 0.95,
        )
    )
    return {
        "is_redacted": find_redactions(slice),
        "text": ocr_slice(slice, 1),
    }


def extract_page(page):

    max_x = 1653
    max_y = 2180
    current_y, last_y, last_y_hit = 0, 0, 0

    page = page.resize((max_x, max_y))
    pil_image = page.convert("RGB")
    open_cv_image = np.array(pil_image)
    open_cv_image = open_cv_image[:, :, ::-1].copy()
    _, _, processed_image = box_extraction(page)

    data = []
    first_key = None
    for row in processed_image:
        if first_key == None:
            first_key = sum(row)
        current_y += 1

        if ((float(sum(row)) / first_key)) * 100 < 25:
            if abs(current_y - last_y) > 2:
                horizontal_slice = processed_image[
                    last_y_hit:current_y, 0:max_x
                ]
                horizontal_slice = cv2.cvtColor(
                    horizontal_slice, cv2.COLOR_GRAY2BGR
                )
                h, _, _ = horizontal_slice.shape
                vertical_slices = [
                    horizontal_slice[:, x, y]
                    for x in range(max_x)
                    for y in range(1)
                ]
                s8 = []
                current_x, last_x, last_x_hit = 0, 0, 0
                for vertical_slice in vertical_slices:
                    current_x += 1
                    if sum(vertical_slice) < 1000:
                        if abs(current_x - last_x) > 2:
                            if last_x_hit > 25:
                                s8.append(
                                    open_cv_image[
                                        last_y_hit:current_y,
                                        last_x_hit:current_x,
                                    ]
                                )
                            last_x_hit = current_x
                        last_x = current_x
                if len(s8) >= 10:
                    if len(s8) == 11:
                        s8 = s8[1:]
                    data.append(s8)
                last_y_hit = current_y
            last_y = current_y
    return data
