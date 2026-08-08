# app.py — PWA + seasonal_theme patch

Your app.py wasn't included in this upload batch, so rather than guess at
its exact current content and risk overwriting something else you've
changed, here are the precise edits to make by hand. Both are small.

===============================================================================
FIX 1 — seasonal_theme was never defined (base.html referenced it but no
route ever set it, so it always rendered empty — harmless with |default('')
but the seasonal color theming feature was silently doing nothing)
===============================================================================

Find this function in app.py:

    @app.context_processor
    def inject_globals():
        current_lang = session.get("lang", app.config["DEFAULT_LANGUAGE"])

        def t(key):
            return get_text(key, current_lang)

        active_banner = None
        try:
            active_banner = Banner.query.filter_by(is_active=True).order_by(Banner.created_at.desc()).first()
        except Exception:  # noqa: BLE001
            pass

        support_telegram_username = None
        try:
            support_telegram_username = get_setting("telegram_support_username")
        except Exception:  # noqa: BLE001
            pass

        return dict(
            t=t,
            current_lang=current_lang,
            available_languages=app.config["LANGUAGES"],
            lang_names={code: TRANSLATIONS[code]["lang.name"] for code in app.config["LANGUAGES"]},
            currency=app.config["CURRENCY_SYMBOL"],
            fx_rates=app.config["FX_RATES"],
            now=datetime.utcnow(),
            active_banner=active_banner,
            media_url=media_url,
            support_telegram_username=support_telegram_username,
        )

ADD a seasonal_theme calculation and include it in the returned dict:

    @app.context_processor
    def inject_globals():
        current_lang = session.get("lang", app.config["DEFAULT_LANGUAGE"])

        def t(key):
            return get_text(key, current_lang)

        active_banner = None
        try:
            active_banner = Banner.query.filter_by(is_active=True).order_by(Banner.created_at.desc()).first()
        except Exception:  # noqa: BLE001
            pass

        support_telegram_username = None
        try:
            support_telegram_username = get_setting("telegram_support_username")
        except Exception:  # noqa: BLE001
            pass

        # Seasonal accent theme (see [data-season="..."] rules in style.css).
        # Date ranges are deliberately generous windows, not exact holiday
        # dates, so the theme doesn't need a redeploy every year. Empty
        # string = no seasonal override, falls back to the normal gold theme.
        seasonal_theme = ""
        today = date.today()
        if (today.month == 12 and today.day >= 15) or (today.month == 1 and today.day <= 2):
            seasonal_theme = "christmas"
        elif today.month == 2 and 10 <= today.day <= 15:
            seasonal_theme = "valentine"
        # Eid dates move every year on the Gregorian calendar (lunar
        # calendar), so there's no fixed month/day range that stays correct
        # long-term — set this manually each year via an AppSetting instead:
        #   set_setting("eid_theme_active", "1")   # turn on
        #   set_setting("eid_theme_active", "0")   # turn off
        try:
            if get_setting("eid_theme_active") == "1":
                seasonal_theme = "eid"
        except Exception:  # noqa: BLE001
            pass

        return dict(
            t=t,
            current_lang=current_lang,
            available_languages=app.config["LANGUAGES"],
            lang_names={code: TRANSLATIONS[code]["lang.name"] for code in app.config["LANGUAGES"]},
            currency=app.config["CURRENCY_SYMBOL"],
            fx_rates=app.config["FX_RATES"],
            now=datetime.utcnow(),
            active_banner=active_banner,
            media_url=media_url,
            support_telegram_username=support_telegram_username,
            seasonal_theme=seasonal_theme,
        )

NOTE: `date` must be imported. Check your top-of-file import line — it's
very likely already there since Coupon/DeliveryZone logic uses dates:

    from datetime import datetime, timedelta, date

If it currently only says `from datetime import datetime, timedelta`, add
`, date` to it.

===============================================================================
FIX 2 — confirm manifest.json / sw.js / icons are served correctly
===============================================================================

No route changes are needed for this — Flask's built-in static file handler
already serves anything placed under the `static/` folder automatically at
`/static/<path>`, which is exactly what `url_for('static', filename=...)`
in base.html resolves to. As long as the files are physically placed at:

    static/manifest.json
    static/sw.js
    static/icons/icon-192.png
    static/icons/icon-192-maskable.png
    static/icons/icon-512.png
    static/icons/icon-512-maskable.png

...nothing in app.py needs to change for them to be reachable. If you want
sw.js to be reachable at the ROOT `/sw.js` instead of `/static/sw.js`
(some browsers are stricter about a service worker's scope matching its
own URL depth), add this small route — otherwise skip it, `/static/sw.js`
works fine for this app since sw.js only needs to control pages under `/`,
which its default scope already covers when registered from a same-origin
page:

    @app.route("/sw.js")
    def service_worker():
        response = app.send_static_file("sw.js")
        response.headers["Service-Worker-Allowed"] = "/"
        return response

If you add this, also update the registration path in base.html from
`{{ url_for('static', filename='sw.js') }}` to `/sw.js` — but again, this
is optional; the current /static/sw.js path already works correctly for
this app's needs.

===============================================================================
FIX 3 — cache-busting reminder
===============================================================================

base.html now requests style.css as `style.css?v=5` (bumped from v=4).
Every time style.css changes going forward, bump this number by one so
browsers/CDNs that cached the old file are forced to re-fetch — this was
very likely the cause of "fixes not showing up" in recent testing.
