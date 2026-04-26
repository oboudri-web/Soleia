/* eslint-disable */
/**
 * Soleia map HTML (Mapbox GL JS + ShadeMap).
 *
 * This is a minimal adaptation of the official mapbox-gl-shadow-simulator
 * Mapbox example by Ted Piotrowski (creator of ShadeMap):
 *   https://github.com/spaste/mapbox-gl-shadow-simulator
 *
 * Adaptations for Soleia:
 *   - Mapbox token + ShadeMap API key swapped for ours
 *   - Center on Nantes (-1.5536, 47.2184), zoom 15
 *   - Style mapbox://styles/mapbox/streets-v12
 *   - All UI control buttons removed
 *   - Mapbox GL JS 3.19.0 + ShadeMap UMD + Suncalc 1.9.0 + Mapbox CSS
 *     all inlined as base64 for offline iOS WebView use
 *   - Two RN bridge functions exposed:
 *       window.setShadeTime(timestamp) -> shadeMap.setDate(new Date(ts))
 *       window.ReactNativeWebView posts {type:'mapReady'} when map loads
 *
 * Two backticks total in this file (template open + close). NO backticks
 * inside any comment within the template. NO non-ASCII characters.
 */
import { MAPBOXJS_B64 } from './mapboxJs';
import { MAPBOXCSS_B64 } from './mapboxCss';
import { SUNCALCJS_B64 } from './suncalcJs';
import { SHADEMAPJS_B64 } from './shadeMapJs';

const MAPBOX_TOKEN_PLACEHOLDER = '__SOLEIA_MAPBOX_TOKEN__';
const SHADEMAP_KEY =
  'eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6Im9ib3VkcmlAZ21haWwuY29tIiwiY3JlYXRlZCI6MTc3NzE5NjQ0NzAwMiwiaWF0IjoxNzc3MTk2NDQ3fQ.Mu6MZW3988d8F4OHMuNQzUllI46EZscid0sFTofwW_o';

export const MAP_HTML = `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <meta http-equiv="X-UA-Compatible" content="ie=edge" />
  <title>Soleia Map</title>
  <style id="mapbox-css-placeholder"></style>
  <style>
    html, body, #mapid {
      padding: 0;
      margin: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #f5f5f5;
      -webkit-tap-highlight-color: transparent;
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      user-select: none;
    }
    .mapboxgl-ctrl-logo, .mapboxgl-ctrl-attrib { display: none !important; }
  </style>
</head>
<body>
  <div id="mapid"></div>

  <script>
    var MAPBOX_CSS_B64 = "${MAPBOXCSS_B64}";
    var MAPBOX_JS_B64 = "${MAPBOXJS_B64}";
    var SUNCALC_JS_B64 = "${SUNCALCJS_B64}";
    var SHADEMAP_JS_B64 = "${SHADEMAPJS_B64}";

    function b64decode(s) { try { return atob(s); } catch (e) { return ''; } }
    function postEarly(p) {
      try {
        if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
          window.ReactNativeWebView.postMessage(JSON.stringify(p));
        }
      } catch (e) {}
    }

    // Inject Mapbox CSS
    try {
      var cssText = b64decode(MAPBOX_CSS_B64);
      var styleEl = document.getElementById('mapbox-css-placeholder');
      if (styleEl) styleEl.textContent = cssText;
      postEarly({ type: 'cssInjected', size: cssText.length });
    } catch (e) { postEarly({ type: 'error', msg: 'css inject failed: ' + e.message }); }

    // Inject Mapbox GL JS
    try {
      var libJs = b64decode(MAPBOX_JS_B64);
      (new Function(libJs))();
      postEarly({ type: 'mapboxInjected', size: libJs.length, hasGlobal: typeof mapboxgl !== 'undefined' });
    } catch (e) { postEarly({ type: 'error', msg: 'mapbox inject failed: ' + e.message }); }

    // Inject Suncalc
    try {
      var sunJs = b64decode(SUNCALC_JS_B64);
      (new Function(sunJs))();
      postEarly({ type: 'suncalcInjected', size: sunJs.length, hasGlobal: typeof SunCalc !== 'undefined' });
    } catch (e) { postEarly({ type: 'error', msg: 'suncalc inject failed: ' + e.message }); }

    // Inject ShadeMap UMD
    try {
      var shadeJs = b64decode(SHADEMAP_JS_B64);
      (new Function(shadeJs))();
      postEarly({ type: 'shadeMapInjected', size: shadeJs.length, hasGlobal: typeof ShadeMap !== 'undefined' });
    } catch (e) { postEarly({ type: 'error', msg: 'shadeMap inject failed: ' + e.message }); }
  </script>

  <script>
    var MAPBOX_TOKEN = (typeof window !== 'undefined' && window.__SOLEIA_MAPBOX_TOKEN__) || '${MAPBOX_TOKEN_PLACEHOLDER}';
    var SHADEMAP_KEY = '${SHADEMAP_KEY}';

    function postToRN(p) {
      try {
        if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
          window.ReactNativeWebView.postMessage(JSON.stringify(p));
        }
      } catch (e) {}
    }

    var mapLoaded = function (map) {
      return new Promise(function (res) {
        function cb() {
          if (!map.loaded()) return;
          map.off('render', cb);
          res();
        }
        map.on('render', cb);
        cb();
      });
    };

    var map = null;
    var shadeMap = null;
    var nowDate = null;

    function init() {
      if (typeof mapboxgl === 'undefined') {
        postToRN({ type: 'error', msg: 'mapboxgl global missing' });
        return;
      }
      mapboxgl.accessToken = MAPBOX_TOKEN;

      map = new mapboxgl.Map({
        container: 'mapid',
        style: 'mapbox://styles/mapbox/streets-v12',
        center: [-1.5536, 47.2184],
        zoom: 15,
      });

      // Initial date: one hour after sunrise at Nantes today (Ted's pattern)
      try {
        var sunTimes = SunCalc.getTimes(new Date(), 47.2184, -1.5536);
        nowDate = new Date(sunTimes.sunrise.getTime() + 60 * 60 * 1000);
      } catch (e) {
        nowDate = new Date();
      }

      map.on('load', function () {
        try {
          shadeMap = new ShadeMap({
            apiKey: SHADEMAP_KEY,
            date: nowDate,
            color: '#01112f',
            opacity: 0.7,
            terrainSource: {
              maxZoom: 15,
              tileSize: 256,
              getSourceUrl: function (args) {
                return 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/' +
                  args.z + '/' + args.x + '/' + args.y + '.png';
              },
              getElevation: function (args) {
                return args.r * 256 + args.g + args.b / 256 - 32768;
              },
            },
            getFeatures: function () {
              return mapLoaded(map).then(function () {
                var feats = map.querySourceFeatures('composite', { sourceLayer: 'building' });
                return (feats || []).filter(function (f) {
                  return f.properties &&
                    f.properties.underground !== 'true' &&
                    (f.properties.height || f.properties.render_height);
                });
              });
            },
            debug: function (msg) { postToRN({ type: 'shadeLog', msg: String(msg) }); },
          }).addTo(map);

          shadeMap.on('tileloaded', function (loaded, total) {
            postToRN({
              type: 'shadeTileProgress',
              loaded: loaded,
              total: total,
              percent: total ? Math.round((loaded / total) * 100) : 0,
            });
          });

          postToRN({ type: 'shadeMapReady' });
        } catch (e) {
          postToRN({ type: 'error', msg: 'ShadeMap init failed: ' + e.message });
        }
        postToRN({ type: 'mapReady' });
      });

      map.on('error', function (ev) {
        postToRN({ type: 'mapError', msg: ev && ev.error ? String(ev.error.message || ev.error) : 'unknown' });
      });
    }

    // ----- Bridge functions exposed to React Native -------------------------

    /** Set ShadeMap simulation date. Accepts ISO string or epoch ms. */
    window.setShadeTime = function (input) {
      try {
        if (!shadeMap) return;
        var d = typeof input === 'number' ? new Date(input) : new Date(String(input));
        if (isNaN(d.getTime())) return;
        nowDate = d;
        shadeMap.setDate(d);
        postToRN({ type: 'shadeLog', msg: 'setDate ' + d.toISOString() });
      } catch (e) {
        postToRN({ type: 'error', msg: 'setShadeTime failed: ' + e.message });
      }
    };

    /** Recenter without animation. */
    window.setCenter = function (lat, lng, zoom) {
      if (!map) return;
      map.jumpTo({ center: [lng, lat], zoom: zoom != null ? zoom : 15 });
    };

    /** Fly the camera to a coordinate. */
    window.flyTo = function (lat, lng, zoom) {
      if (!map) return;
      map.flyTo({ center: [lng, lat], zoom: zoom != null ? zoom : 16, duration: 800 });
    };

    document.addEventListener('DOMContentLoaded', function () {
      try { init(); postToRN({ type: 'htmlLoaded' }); }
      catch (e) { postToRN({ type: 'error', msg: 'init threw: ' + e.message }); }
    });
  </script>
</body>
</html>`;
