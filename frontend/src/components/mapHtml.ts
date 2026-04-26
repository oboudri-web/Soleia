/**
 * Soleia — Map HTML as JavaScript string.
 *
 * The WebView consumes this via <WebView source={{ html: MAP_HTML }} />.
 *
 * Self-contained — does NOT load anything from CDN. MapLibre GL JS,
 * MapLibre CSS and ShadeMap (mapbox-gl-shadow-simulator) are inlined as
 * base64 and decoded in the page via atob() before use. Avoids unpkg/CDN
 * blockage on iOS production builds (offline behaviour, App Store review).
 *
 * Network requests at runtime are limited to:
 *   • MapTiler tiles & style.json
 *   • MapTiler terrain-rgb-v2 tiles (for ShadeMap elevation)
 *   • ShadeMap API key validation (api.shademap.app)
 */
import { MAPLIBREJS_B64 } from './mapLibreJs';
import { MAPLIBRECSS_B64 } from './mapLibreCss';
import { SHADEMAPJS_B64 } from './shadeMapJs';

const MAPTILER_KEY = 'PrVP1L26j30UHcrnm87w';
const SHADEMAP_KEY =
  'eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6Im9ib3VkcmlAZ21haWwuY29tIiwiY3JlYXRlZCI6MTc3NzE5NjQ0NzAwMiwiaWF0IjoxNzc3MTk2NDQ3fQ.Mu6MZW3988d8F4OHMuNQzUllI46EZscid0sFTofwW_o';

// The big inline map page. We use String.raw to avoid backtick-collision with
// any minified JS that might contain backticks (we still must escape ` and ${
// in the body — but our body is hand-written so we use plain template here and
// keep external libs in base64 vars decoded at runtime via atob()).
export const MAP_HTML = `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Soleia Map</title>
  <style id="maplibre-css-placeholder"></style>
  <style>
    html, body, #map {
      margin: 0;
      padding: 0;
      width: 100%;
      height: 100%;
      overflow: hidden;
      background: #f5f5f5;
      -webkit-tap-highlight-color: transparent;
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      user-select: none;
    }
    .maplibregl-ctrl-attrib { display: none !important; }
    .maplibregl-ctrl-logo { display: none !important; }
  </style>
</head>
<body>
  <div id="map"></div>

  <script>
    // ─── Inlined libs (base64) ────────────────────────────────────────────
    var MAPLIBRE_CSS_B64 = "${MAPLIBRECSS_B64}";
    var MAPLIBRE_JS_B64 = "${MAPLIBREJS_B64}";
    var SHADEMAP_JS_B64 = "${SHADEMAPJS_B64}";

    // Base64 → string (UTF-8 safe). Modern WKWebView supports atob natively.
    function b64decode(s) {
      try {
        // atob handles ASCII; minified JS is ASCII-only so this is fine.
        return atob(s);
      } catch (e) {
        return '';
      }
    }

    function postEarly(payload) {
      try {
        if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
          window.ReactNativeWebView.postMessage(JSON.stringify(payload));
        }
      } catch (e) {}
    }

    // Inject the MapLibre CSS into the head
    try {
      var cssText = b64decode(MAPLIBRE_CSS_B64);
      var styleEl = document.getElementById('maplibre-css-placeholder');
      if (styleEl) styleEl.textContent = cssText;
      postEarly({ type: 'cssInjected', size: cssText.length });
    } catch (e) {
      postEarly({ type: 'error', msg: 'css inject failed: ' + e.message });
    }

    // Eval the MapLibre JS bundle (~800KB)
    try {
      var libJs = b64decode(MAPLIBRE_JS_B64);
      // Use Function constructor instead of eval so it runs in global scope cleanly.
      (new Function(libJs))();
      postEarly({ type: 'maplibreInjected', size: libJs.length, hasGlobal: typeof maplibregl !== 'undefined' });
    } catch (e) {
      postEarly({ type: 'error', msg: 'maplibre inject failed: ' + e.message });
    }

    // Eval the ShadeMap UMD bundle (~74KB)
    try {
      var shadeJs = b64decode(SHADEMAP_JS_B64);
      (new Function(shadeJs))();
      postEarly({ type: 'shadeMapInjected', size: shadeJs.length, hasGlobal: typeof ShadeMap !== 'undefined' });
    } catch (e) {
      postEarly({ type: 'error', msg: 'shadeMap inject failed: ' + e.message });
    }
  </script>

  <script>
    var MAPTILER_KEY = '${MAPTILER_KEY}';
    var SHADEMAP_KEY = '${SHADEMAP_KEY}';
    var STYLE_URL = 'https://api.maptiler.com/maps/streets/style.json?key=' + MAPTILER_KEY;
    var TERRAIN_URL_TEMPLATE = 'https://api.maptiler.com/tiles/terrain-rgb-v2/{z}/{x}/{y}.webp?key=' + MAPTILER_KEY;

    function postToRN(payload) {
      try {
        if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
          window.ReactNativeWebView.postMessage(JSON.stringify(payload));
        }
      } catch (e) {}
    }

    var map = null;
    var shadeMap = null;
    var terraces = [];
    var viewportPostScheduled = false;

    function initMap(initialCenter, initialZoom) {
      if (typeof maplibregl === 'undefined') {
        postToRN({ type: 'error', msg: 'maplibregl global missing — bundle eval failed' });
        return;
      }
      map = new maplibregl.Map({
        container: 'map',
        style: STYLE_URL,
        center: initialCenter || [-1.5536, 47.2184],
        zoom: initialZoom != null ? initialZoom : 14,
        pitch: 45,
        bearing: 0,
        attributionControl: false,
        maxPitch: 70,
        antialias: true,
      });

      map.touchZoomRotate.enable();
      map.dragRotate.enable();

      map.on('load', function () {
        postToRN({ type: 'mapReady' });

        // ─── Masquer les couches POI/transit pour alléger la carte ────────
        // Style "Apple Maps" : on garde routes, bâtiments, eau, parcs. Tous
        // les POI/transit/parkings/airports etc. sont cachés. Les seuls POI
        // visibles sur la carte sont nos markers terrasses Soleia.
        try {
          var layersToHide = [
            'poi', 'poi-label', 'transit-label',
            'airport-label', 'parking', 'parking-label',
            'bus-stop', 'tram-stop', 'subway-station',
            'railway', 'ferry',
          ];
          var hiddenCount = 0;
          var allLayers = map.getStyle().layers || [];
          for (var i = 0; i < allLayers.length; i++) {
            var lyr = allLayers[i];
            var lid = lyr.id || '';
            for (var j = 0; j < layersToHide.length; j++) {
              if (lid.indexOf(layersToHide[j]) !== -1) {
                try {
                  map.setLayoutProperty(lid, 'visibility', 'none');
                  hiddenCount++;
                } catch (innerErr) {}
                break;
              }
            }
          }
          postToRN({ type: 'layersHidden', count: hiddenCount, total: allLayers.length });
        } catch (e) {
          postToRN({ type: 'error', msg: 'layer hide failed: ' + e.message });
        }

        try {
          if (typeof ShadeMap !== 'undefined') {
            shadeMap = new ShadeMap({
              date: new Date(),
              color: '#01112f',
              opacity: 0.7,
              apiKey: SHADEMAP_KEY,
              terrainSource: {
                tileSize: 514,
                maxZoom: 12,
                getSourceUrl: function (args) {
                  return TERRAIN_URL_TEMPLATE
                    .replace('{x}', args.x)
                    .replace('{y}', args.y)
                    .replace('{z}', args.z);
                },
                getElevation: function (args) {
                  return -10000 + (args.r * 256 * 256 + args.g * 256 + args.b) * 0.1;
                },
              },
              debug: function (msg) { postToRN({ type: 'shadeLog', msg: String(msg) }); },
            }).addTo(map);
            postToRN({ type: 'shadeMapReady' });
          } else {
            postToRN({ type: 'error', msg: 'ShadeMap library not loaded (global missing)' });
          }
        } catch (e) {
          postToRN({ type: 'error', msg: 'ShadeMap init failed: ' + (e && e.message ? e.message : String(e)) });
        }
      });

      map.on('error', function (ev) {
        postToRN({ type: 'mapError', msg: ev && ev.error ? String(ev.error.message || ev.error) : 'unknown' });
      });

      var scheduleViewportPost = function () {
        if (viewportPostScheduled) return;
        viewportPostScheduled = true;
        requestAnimationFrame(function () {
          viewportPostScheduled = false;
          postViewport();
        });
      };

      map.on('move', scheduleViewportPost);
      map.on('zoom', scheduleViewportPost);
      map.on('rotate', scheduleViewportPost);
      map.on('pitch', scheduleViewportPost);
      map.on('moveend', postViewport);
    }

    function postViewport() {
      if (!map) return;
      var c = map.getCenter();
      var points = [];
      for (var i = 0; i < terraces.length; i++) {
        var t = terraces[i];
        if (typeof t.lat !== 'number' || typeof t.lng !== 'number') continue;
        var p = map.project([t.lng, t.lat]);
        points.push({
          id: t.id,
          x: Math.round(p.x),
          y: Math.round(p.y),
          sunny: t.sun_status === 'sunny' ? 1 : 0,
        });
      }
      var b = map.getBounds();
      postToRN({
        type: 'viewport',
        center: { lat: c.lat, lng: c.lng },
        zoom: map.getZoom(),
        bearing: map.getBearing(),
        pitch: map.getPitch(),
        bounds: {
          lat_min: b.getSouth(),
          lat_max: b.getNorth(),
          lng_min: b.getWest(),
          lng_max: b.getEast(),
        },
        points: points,
      });
    }

    window.updateTerraces = function (list) {
      try {
        terraces = Array.isArray(list) ? list : [];
        postToRN({ type: 'terracesAck', count: terraces.length });
        postViewport();
      } catch (e) {
        postToRN({ type: 'error', msg: 'updateTerraces failed: ' + e.message });
      }
    };

    window.setShadeTime = function (input) {
      try {
        if (!shadeMap) { postToRN({ type: 'shadeLog', msg: 'setShadeTime ignored — shadeMap not ready' }); return; }
        var d = typeof input === 'number' ? new Date(input) : new Date(String(input));
        if (isNaN(d.getTime())) return;
        shadeMap.setDate(d);
        postToRN({ type: 'shadeLog', msg: 'setDate ' + d.toISOString() });
      } catch (e) {
        postToRN({ type: 'error', msg: 'setShadeTime failed: ' + e.message });
      }
    };

    window.flyTo = function (lat, lng, zoom) {
      if (!map) return;
      map.flyTo({ center: [lng, lat], zoom: zoom != null ? zoom : 16, pitch: 45, duration: 800 });
    };

    window.setCenter = function (lat, lng, zoom) {
      if (!map) return;
      map.jumpTo({ center: [lng, lat], zoom: zoom != null ? zoom : 14 });
    };

    window.setShadeOpacity = function (opacity) {
      if (!shadeMap) return;
      try { shadeMap.setOpacity(opacity); } catch (e) {}
    };

    document.addEventListener('DOMContentLoaded', function () {
      try {
        initMap();
        postToRN({ type: 'htmlLoaded' });
      } catch (e) {
        postToRN({ type: 'error', msg: 'initMap threw: ' + e.message });
      }
    });
  </script>
</body>
</html>`;
