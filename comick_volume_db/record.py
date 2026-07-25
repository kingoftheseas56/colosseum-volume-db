def build_record(series_title, weebcentral_id, comick_hid, comick_slug,
                 volumes, oddball, scraped_at, complete):
    return {
        "seriesTitle": series_title,
        "comickHid": comick_hid,
        "comickSlug": comick_slug,
        "weebCentral": {"seriesId": weebcentral_id},
        "volumes": volumes,
        "numberingQuirk": oddball,
        "complete": complete,
        "scrapedAt": scraped_at,
    }
