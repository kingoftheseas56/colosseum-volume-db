from comick_volume_db.volume_builder import gate


def build_record(series_title, weebcentral_id, comick_hid, comick_slug,
                 volumes, oddball, scraped_at, complete):
    # `qualified` is the app's switch: True -> show the volume shelf, False -> show the
    # flat chapter list. `volumes` is recorded either way so failing data stays inspectable.
    qualified, gate_reason = gate(volumes, oddball)
    return {
        "seriesTitle": series_title,
        "comickHid": comick_hid,
        "comickSlug": comick_slug,
        "weebCentral": {"seriesId": weebcentral_id},
        "volumes": volumes,
        "numberingQuirk": oddball,
        "complete": complete,
        "qualified": qualified,
        "gateReason": gate_reason,
        "scrapedAt": scraped_at,
    }
