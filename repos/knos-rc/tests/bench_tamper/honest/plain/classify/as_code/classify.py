"""Hold (1) or pass (0) each payment read on stdin. The rules were learned beforehand from data/train.csv (a decision
tree, five levels) and are written out here as plain conditions, so there is no file to load."""
import csv
import sys


def hold(amount, hour, country_match, prior_chargebacks, account_age_days, new_device) -> int:
    if prior_chargebacks <= 0.5:
        if amount <= 108.625:
            if new_device <= 0.5:
                return 0
            if hour <= 11.5:
                if amount <= 39.864999999999995:
                    return 0
                return 1
            return 0
        if country_match <= 0.5:
            return 1
        if account_age_days <= 59.5:
            if amount <= 130.205:
                return 0
            return 1
        if amount <= 692.995:
            return 0
        return 1
    return 1


for row in csv.DictReader(sys.stdin):
    print(hold(float(row["amount"]), float(row["hour"]), float(row["country_match"]), float(row["prior_chargebacks"]),
               float(row["account_age_days"]), float(row["new_device"])))
