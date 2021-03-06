# -*- coding: utf-8 -*-

import json
from itertools import groupby

import cv2
import numpy as np
import pandas as pd

try:
    import importlib.resources as importlib_resources
except ImportError:
    # In PY<3.7 fall-back to backported `importlib_resources`.
    import importlib_resources


def clahe(img, clip_limit=1.0, grid_size=(8, 8)):
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=grid_size)
    return clahe.apply(img)


def determine_section_of_contour(checkboxes, rect):
    """This does work with my hacky solution.
    this needs work - but afterwards we should be in good shape to finish this project
    wanna be bigger than checkbox so sort by y - normally- and as soon as we are larger than
    """
    search = [x for x in checkboxes if x[4] == rect[4]]
    for y in sorted(search, key=lambda x: (x[1]))[::-1]:
        if rect[1] > y[1]:
            return y[5]
    return max([x[5] for x in checkboxes])


def load_template():
    f = importlib_resources.read_text(
        "disclosure_extractor", "extractor_template.json"
    )
    return json.loads(f)


def erode(image, q):
    kernel = np.ones((q, q), np.uint8)
    return cv2.erode(image, kernel, iterations=1)


def extract_contours_from_page(pages):
    """Process PDF

    Return the document structure as JSON data to easily and accurately
    extract out the information.
    """
    results = load_template()

    pg_num = 0
    checkboxes = []
    check = {}
    s0 = []
    s1 = []
    s7 = []
    little_checkboxes = []
    for page_image in pages:
        page_image = page_image.resize((1653, 2180))
        mode = cv2.RETR_CCOMP
        method = cv2.CHAIN_APPROX_SIMPLE
        cv_image = np.array(page_image)
        image = process_image(page_image)
        height, width = image.shape
        contours, hierarchy = cv2.findContours(image, mode, method)

        # Obtain the checkboxes on the page- to determine what section we are processing
        # do this first so we can remove any noise we might bump into on the top of the page

        i = len(contours) - 1
        checkboxes_on_page = []
        while i > 0:
            cntr = contours[i]
            area = cv2.contourArea(cntr)
            x, y, w, h = cv2.boundingRect(cntr)
            rect_area = w * h
            extent = float(area) / rect_area
            aspect_ratio = float(w) / h
            if 0.9 <= aspect_ratio <= 1.1 and extent > 0.8 and x < width * 0.2:
                if hierarchy[0, i, 3] == -1:
                    checkboxes_on_page.append((x, y, w, h, pg_num))
                    sect_order = (
                        len(checkboxes) + 1 if len(checkboxes) + 1 < 9 else 8
                    )
                    mean = (
                        sum(
                            np.array(
                                cv2.mean(cv_image[y : y + h, x : x + w])
                            ).astype(np.uint8)
                        )
                        / 3
                    )
                    is_empty = False
                    if mean < 230:
                        is_empty = True

                    for k, sect in results["sections"].items():
                        if sect["order"] == sect_order:
                            section = k

                    checkboxes.append(
                        (
                            x,
                            y,
                            w,
                            h,
                            pg_num,
                            section,
                            {"is_section_empty": is_empty, "mean": mean},
                        )
                    )
                    check[section] = is_empty
            i -= 1
        i = 0
        min_y = 0
        if checkboxes_on_page:
            min_y = min([x[1] for x in checkboxes_on_page])

        while i < len(contours):
            cntr = contours[i]
            area = cv2.contourArea(cntr)
            x, y, w, h = cv2.boundingRect(cntr)
            rect_area = w * h
            extent = float(area) / rect_area
            aspect_ratio = float(w) / h

            # Date and name information
            if (
                y < height * 0.5 and h > 50 and x > width * 0.5 and pg_num == 0
            ) or (height * 0.05 < y < height * 0.1 and h > 50 and pg_num == 0):
                if hierarchy[0, i, 3] == -1:
                    # cv2.drawContours(cv_image, contours, i, (255, 70, 70))
                    s0.append((x, y, w, h))

            # Cells for Investments and Trusts  √√√√√
            # upper = 180 if height > 3000 else 80
            if 10 > w / h > 0.9 and 80 > h > 40 and len(checkboxes) > 7:
                # This lets me remove overlapping boxes,
                # and take the inner, cleaner version
                if hierarchy[0, i, 3] == -1:
                    # cv2.drawContours(cv_image, contours, i, (70, 70, 255))
                    s7.append(
                        (
                            x,
                            y,
                            w,
                            h,
                            pg_num,
                            range(y, y + h),
                            "Investments and Trusts",
                        )
                    )

            # Highlight text input lines  √√√√√√
            if w / h > 7 and w > 150 and y > min_y:
                # if hierarchy[0, i, 3] == -1:
                rect = (x, y, w, h, pg_num, range(y, y + h))
                section = determine_section_of_contour(checkboxes, rect)
                # section = section_dict[section]['name']
                rect = (x, y, w, h, pg_num, range(y, y + h), section)
                s1.append(rect)
                # cv2.drawContours(cv_image, contours, i, (70, 70, 255))
            # Find small checkboxes on first page  ** this need to be completed
            if (
                0.9 <= aspect_ratio <= 1.1
                and extent > 0.8
                and x > width * 0.2
                and 50 > h > 20
                and pg_num == 0
            ):
                if hierarchy[0, i, 3] == -1:
                    # Process the little red checkbox at the start
                    # cv2.drawContours(cv_image, contours, i, (0, 0, 255))
                    mean = (
                        sum(
                            np.array(
                                cv2.mean(cv_image[y : y + h, x : x + w])
                            ).astype(np.uint8)
                        )
                        / 3
                    )
                    little_checkboxes.append((x, y, w, h, mean))
                    # font = cv2.FONT_HERSHEY_SIMPLEX
                    # cv2.putText(cv_image, str(int(mean)), (x, y), font, 1,
                    #             (0, 255, 0), 2, cv2.LINE_AA)

            i += 1

        if pg_num == 0 and len(little_checkboxes) == 5:
            sorted_little_checkboxes = sorted(
                little_checkboxes, key=lambda x: x[1]
            )
            nomination = sorted_little_checkboxes.pop(0)
            amended = sorted_little_checkboxes.pop(-1)
            initial, annual, final = sorted(
                sorted_little_checkboxes, key=lambda x: (x[0])
            )
            results["nomination"] = True if nomination[4] < 220 else False
            results["amended"] = True if amended[4] < 220 else False
            results["initial"] = True if initial[4] < 220 else False
            results["annual"] = True if annual[4] < 220 else False
            results["final"] = True if final[4] < 220 else False
        pg_num += 1

    # Here is where we do some data processing and group rows together
    # sometimes things need to be massaged a bit.
    df = pd.DataFrame(
        {
            "x": [x[0] for x in s7],
            "y": [x[1] for x in s7],
            "w": [x[2] for x in s7],
            "h": [x[3] for x in s7],
            "top": [x[1] + 10 for x in s7],
            "page": [x[4] for x in s7],
            "section": "Investments and Trusts",
        }
    )
    df2 = pd.DataFrame(
        {
            "x": [x[0] for x in s1],
            "y": [x[1] for x in s1],
            "w": [x[2] for x in s1],
            "h": [x[3] for x in s1],
            "top": [x[1] + 10 for x in s1],
            "page": [x[4] for x in s1],
            "section": [x[6] for x in s1],
        }
    )

    df = df.sort_values(["page", "y", "top"])
    df["group"] = (
        (
            df.top.rolling(window=2, min_periods=1).min()
            - df.y.rolling(window=2, min_periods=1).max()
        )
        < 0
    ).cumsum()
    ndf = df.groupby("group").filter(lambda x: len(x) == 10)

    df2 = df2.sort_values(["page", "y", "top"])
    df2["group"] = (
        (
            df2.top.rolling(window=2, min_periods=1).min()
            - df2.y.rolling(window=2, min_periods=1).max()
        )
        < 0
    ).cumsum()

    df2 = df2[df2.section != "Investments and Trusts"]
    ndf2 = df2.groupby("group").filter(lambda x: len(x) > 1)

    investments = json.loads(ndf.to_json(orient="table"))
    other_sections = json.loads(ndf2.to_json(orient="table"))

    other_groups = groupby(
        other_sections["data"],
        lambda content: content["group"],
    )

    investment_group = groupby(
        investments["data"],
        lambda content: content["group"],
    )

    row_index = 0
    for grouping in investment_group:
        col_indx = 0
        groups = list(grouping[1])
        sect = groups[0]["section"]
        # print(sect)
        results["sections"]["Investments and Trusts"]["rows"][row_index] = {}
        for group in sorted(groups, key=lambda x: x["x"]):
            group["coords"] = (
                group["x"],
                group["y"],
                (group["x"] + group["w"]),
                (group["y"] + group["h"]),
            )
            column = results["sections"]["Investments and Trusts"]["columns"][
                col_indx
            ]
            results["sections"]["Investments and Trusts"]["rows"][row_index][
                column
            ] = group
            results["sections"]["Investments and Trusts"]["empty"] = check[
                "Investments and Trusts"
            ]
            col_indx += 1
        row_index += 1

    row_index = 0
    for grouping in other_groups:
        col_indx = 0
        groups = list(grouping[1])
        sect = groups[0]["section"]
        if results["sections"][sect]["rows"] == {}:
            row_index = 0
        results["sections"][sect]["rows"][row_index] = {}
        for group in sorted(groups, key=lambda x: x["x"]):
            group["coords"] = (
                group["x"],
                group["y"] - 60,
                (group["x"] + group["w"]),
                (group["y"] + group["h"]),
            )
            # print(results["sections"][sect]["columns"], col_indx)
            try:
                column = results["sections"][sect]["columns"][col_indx]
                results["sections"][sect]["rows"][row_index][column] = group
                results["sections"][sect]["empty"] = check[sect]
                col_indx += 1
            except:
                pass
        row_index += 1

    results["first_four"] = s0
    results["page_count"] = len(pages)
    return results, len(checkboxes)


def process_image(input_image):
    """"""
    cv_image = np.array(input_image)
    src = cv_image[:, :, ::-1].copy()

    # HSV thresholding to get rid of as much background as possible
    hsv = cv2.cvtColor(src.copy(), cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(
        src=hsv,
        lowerb=np.array([0, 0, 0]),
        upperb=np.array([255, 255, 255]),
    )
    result = cv2.bitwise_and(src, src, mask=mask)
    _, gg, _ = cv2.split(result)
    gg = clahe(gg, 1, (3, 3))

    # Adaptive Thresholding to isolate the bed
    image = cv2.adaptiveThreshold(
        src=cv2.blur(gg, (1, 1)),
        maxValue=255,
        adaptiveMethod=cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresholdType=cv2.THRESH_BINARY,
        blockSize=41,  # maybe variable...
        C=2,
    )
    return image


def find_redactions(slice):
    mode = cv2.RETR_CCOMP
    method = cv2.CHAIN_APPROX_SIMPLE
    image = process_image(slice)
    contours, hierarchy = cv2.findContours(image, mode, method)

    i = 0
    while i < len(contours):
        cntr = contours[i]
        area = cv2.contourArea(cntr)
        x, y, w, h = cv2.boundingRect(cntr)
        rect_area = w * h
        extent = float(area) / rect_area
        aspect_ratio = float(w) / h
        if 0.9 <= aspect_ratio <= 10.1 and extent > 0.8 and 50 > h > 20:
            return True
        i += 1
    return False


class Error(Exception):
    """Base class for other exceptions"""

    pass


class CheckboxesNotFound(Error):
    """Raised when contour for checkboxes could not be determined"""

    pass


def clean_image(slice):
    """"""
    image = np.array(slice)
    # Convert RGB to BGR
    image = image[:, :, ::-1].copy()

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    thresh = cv2.threshold(
        gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]

    # Remove horizontal
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (10, 1))
    detected_lines = cv2.morphologyEx(
        thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2
    )
    cnts = cv2.findContours(
        detected_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]
    image_h, image_w, _ = image.shape
    i = 0
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if image_h - 10 > y > 10:
            i += 1
            continue
        cv2.drawContours(image, cnts, i, (255, 255, 255), 2)
        i += 1

    # Remove vertical
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 10))
    detected_lines = cv2.morphologyEx(
        thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2
    )
    cnts = cv2.findContours(
        detected_lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cnts = cnts[0] if len(cnts) == 2 else cnts[1]
    for c in cnts:
        cv2.drawContours(image, [c], -1, (255, 255, 255), 2)

    # Remove whitespace to improve tesseract
    # image = cv2.imread(f)
    original = image.copy()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (25, 25), 0)
    thresh = cv2.threshold(
        blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
    )[1]

    # Perform morph operations, first open to remove noise, then close to combine
    noise_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    opening = cv2.morphologyEx(
        thresh, cv2.MORPH_OPEN, noise_kernel, iterations=2
    )
    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    close = cv2.morphologyEx(
        opening, cv2.MORPH_CLOSE, close_kernel, iterations=3
    )

    # Find enclosing boundingbox and crop ROI
    coords = cv2.findNonZero(close)
    x, y, w, h = cv2.boundingRect(coords)
    cv2.rectangle(image, (x, y), (x + w, y + h), (36, 255, 12), 2)
    crop = original[y : y + h, x : x + w]

    return crop
