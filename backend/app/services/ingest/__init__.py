"""Files as people export them: recognised, and put in the shape the analysis reads.

A person who does not know what a CSV is exports a list from the program they
already use and drops it in. They do not pick a "source type", rename columns
to English, or reformat "45.000,00". This package works out what the file is
(`recognize`) and rewrites it into the columns and formats each domain's
parser reads (`normalize`).
"""
