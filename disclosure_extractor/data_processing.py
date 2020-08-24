import collections
import logging
import re
from itertools import groupby

import pytesseract

from disclosure_extractor.image_processing import find_redactions

investment_components = {
    1: {
        "roman_numeral": "I",
        "name": "Positions",
        "fields": ["Position", "Name of Organization/Entity"],
    },
    2: {
        "roman_numeral": "II",
        "name": "Agreements",
        "fields": ["Date", "Parties and Terms"],
    },
    3: {
        "roman_numeral": "IIIA",
        "name": "Non-Investment Income",
        "fields": ["Date", "Source and Type", "Income"],
    },
    4: {
        "roman_numeral": "IIIB",
        "name": "Spouse's Non-Investment Income",
        "fields": ["Date", "Source and Type"],
    },
    5: {
        "roman_numeral": "IV",
        "name": "Reimbursements",
        "fields": [
            "Sources",
            "Dates",
            "Location",
            "Purpose",
            "Items Paid or Provided",
        ],
    },
    6: {
        "roman_numeral": "V",
        "name": "Gifts",
        "fields": ["Source", "Description", "Value"],
    },
    7: {
        "roman_numeral": "VI",
        "name": "Liabilities",
        "fields": ["Creditor", "Description", "Value Code"],
    },
    8: {
        "roman_numeral": "VII",
        "name": "Investments and Trusts",
        "fields": [
            "A Description of Asset",
            "B Amount Code",
            "B Type",
            "C Value Code",
            "C Value Method",
            "C Type",
            "D Date",
            "D Value Code",
            "D Gain Code",
            "D Identity of Buyer/Seller",
        ],
    },
}


def ocr_page(image):
    text = pytesseract.image_to_string(
        image, config="-c preserve_interword_spaces=1x1 --psm %s --oem 3" % 6
    )
    text = text.replace("\n", " ").strip().replace("|", "")
    return re.sub(" +", " ", text)


def ocr_date(image):
    """OCR date string from image slice

    """
    text = pytesseract.image_to_string(
        image,
        config="-c tessedit_char_whitelist=01234567890./: preserve_interword_spaces=1x1 --psm %s --oem 3"
        % 11,
    )
    text = text.replace("\n", " ").strip().replace("|", "")
    text = re.sub(" +", " ", text)
    return text


def ocr_variables(slice, column):
    """
    Values range from A to H

    :param file_path:
    :return:
    """
    if column == 2 or column == 9:
        possibilities = ["A", "B", "C", "D", "E", "F", "G", "H"]
    elif column == 5:
        possibilities = ["Q", "R", "S", "T", "U", "V", "W"]
    else:
        possibilities = [
            "J",
            "K",
            "L",
            "M",
            "N",
            "O",
            "P1",
            "P2",
            "P3",
            "P4",
        ]

    for v in [6, 7, 10]:
        text = pytesseract.image_to_string(
            slice, config="--psm %s --oem 3" % v
        )
        clean_text = text.replace("\n", "").strip().upper().strip(".")
        if clean_text == "PL" or clean_text == "PI" or clean_text == "P|":
            return "P1"
        if len(clean_text) > 0:
            if clean_text in possibilities:
                if len(clean_text) > 0:
                    return clean_text
        if len(clean_text) == 2:
            return clean_text[0]
    return text.replace("\n", " ").strip()


def ocr_slice(rx, count):
    """

    """
    rx.convert("RGBA")
    data = rx.getdata()
    counts = collections.Counter(data)
    if (
        len(counts)
        < 50  # this number needs to fluctuate - or i need to find a way to create this in code,
        #     Current ideas is to grab a predictable slice of page that is white and sample it and use that number as a threshold
    ):  # this may need to fluctuate to be accurate at dropping empty sections to remove gibberish
        return ""
    if count == 1 or count == 6 or count == 10 or count == 3:
        text = ocr_page(rx)
    elif count == 7:
        text = ocr_date(rx)
    elif count == 4 or count == 8 or count == 2 or count == 9 or count == 5:
        text = ocr_variables(rx, count)
    return text


def generate_row_data(slice, row, column_index, row_index):
    """

    """
    cd = {}
    section = investment_components[row["section"]]["name"]
    cd["section"] = section
    cd["title"] = investment_components[row["section"]]["roman_numeral"]
    cd["field"] = investment_components[row["section"]]["fields"][column_index]

    cd["redactions"] = find_redactions(slice)
    cd["column_index"] = column_index
    cd["row_index"] = row_index
    return cd


def process_document(document_structure, pages):
    results = {
        "Positions": {"empty": None, "content": []},
        "Agreements": {"empty": None, "content": []},
        "Non-Investment Income": {"empty": None, "content": []},
        "Spouse's Non-Investment Income": {"empty": None, "content": []},
        "Reimbursements": {"empty": None, "content": []},
        "Gifts": {"empty": None, "content": []},
        "Liabilities": {"empty": None, "content": []},
        "Investments and Trusts": {"empty": None, "content": []},
    }

    checkboxes = [
        {x[5]: x[6]["is_section_empty"]}
        for x in document_structure["checkboxes"]
    ]
    for v in checkboxes:
        for i in v.keys():
            category = investment_components[i]["name"]
            results[category]["empty"] = v[i]

    parts = ["all_other_sections", "investments_and_trusts"]
    for part in parts:
        if part == "all_other_sections":
            logging.info("Processing §§ I. to VI.")
        else:
            logging.info("Processing §VII.")
        groups = groupby(
            document_structure[part], lambda content: content["group"],
        )
        adjustment = 0 if part == "investments_and_trusts" else 60
        row_index = 0
        for grouping in groups:
            column_index = 0
            for row in sorted(grouping[1], key=lambda x: x["x"]):
                ocr_key = (
                    1 if part == "all_other_sections" else column_index + 1
                )
                slice = pages[row["page"]].crop(
                    (
                        row["x"],
                        row["y"] - adjustment,
                        (row["x"] + row["w"]),
                        (row["y"] + row["h"]),
                    )
                )
                section = investment_components[row["section"]]["name"]
                cd = generate_row_data(slice, row, column_index, row_index)
                cd["text"] = ocr_slice(slice, ocr_key)

                content = results[section]["content"]
                content.append(cd)
                results[section]["content"] = content
                column_index += 1
            row_index += 1

    width, height = pages[-2].size
    slice = pages[-2].crop((0, height * 0.15, width, height * 0.95,))
    results["Additional Information"] = {
        "section": "Additional Information",
        "title": "VIII",
        "redactions": find_redactions(slice),
        "text": ocr_slice(slice, 1),
    }

    i = 0
    four = ["reporting_period", "date_of_report", "court", "judge"]
    for one in document_structure["first_four"]:
        if i > 0:
            slice = pages[0].crop(
                (
                    one[0],
                    one[1] * 1.2,
                    one[0] + one[2],
                    one[1] * 1.2 + one[3] * 0.7,
                )
            )
        else:
            slice = pages[0].crop(
                (one[0], one[1], one[0] + one[2], one[1] + one[3])
            )
        results[four[i]] = ocr_slice(slice, 1).replace("\n", " ").strip()
        i += 1
    return results
