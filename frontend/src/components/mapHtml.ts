/* eslint-disable */
/**
 * Soleia map HTML.
 *
 * Architecture inspired by SunSeekr's stack:
 *  - MapLibre GL JS as map engine (aliased to window.mapboxgl for ShadeMap compat)
 *  - CARTO Voyager Free style (no API key)
 *  - ShadeMap with AWS terrarium DEM (free public bucket)
 *  - Native MapLibre markers (much more reliable than RN absolute overlays)
 *
 * Visual identity is fully Soleia: orange F5A623, French labels, custom emoji
 * icons (bar / cafe / restaurant / rooftop), and personalized terrace polygons.
 *
 * Two backticks only in this file: open of MAP_HTML on line 28 and close near
 * the end. NO backticks in any comment inside the template (otherwise the
 * Hermes parser closes the template literal early - real bug we hit before).
 *
 * NO accented characters in this file - Hermes was strict on UTF-8 multi-byte
 * chars in some embedded comments. Plain ASCII only.
 */
import { MAPLIBREJS_B64 } from './mapLibreJs';
import { MAPLIBRECSS_B64 } from './mapLibreCss';
import { SHADEMAPJS_B64 } from './shadeMapJs';

const SHADEMAP_KEY =
  'eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6Im9ib3VkcmlAZ21haWwuY29tIiwiY3JlYXRlZCI6MTc3NzE5NjQ0NzAwMiwiaWF0IjoxNzc3MTk2NDQ3fQ.Mu6MZW3988d8F4OHMuNQzUllI46EZscid0sFTofwW_o';

export const MAP_HTML = `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8" />
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
      background: #f6f3ee;
      -webkit-tap-highlight-color: transparent;
      -webkit-touch-callout: none;
      -webkit-user-select: none;
      user-select: none;
    }
    .maplibregl-ctrl-attrib { display: none !important; }
    .maplibregl-ctrl-logo { display: none !important; }
    .soleia-marker {
      width: 36px;
      height: 36px;
      border-radius: 50%;
      background: #ffffff;
      box-shadow: 0 2px 8px rgba(0,0,0,0.25);
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      font-size: 16px;
      transition: border-color 200ms ease, filter 200ms ease, opacity 200ms ease, transform 150ms ease;
    }
    .soleia-marker.selected {
      transform: scale(1.18);
      box-shadow: 0 4px 14px rgba(245,166,35,0.55);
    }
  </style>
</head>
<body>
  <div id="map"></div>

  <script>
    var MAPLIBRE_CSS_B64 = "${MAPLIBRECSS_B64}";
    var MAPLIBRE_JS_B64 = "${MAPLIBREJS_B64}";
    var SHADEMAP_JS_B64 = "${SHADEMAPJS_B64}";

    function b64decode(s) { try { return atob(s); } catch (e) { return ''; } }
    function postEarly(p) {
      try {
        if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
          window.ReactNativeWebView.postMessage(JSON.stringify(p));
        }
      } catch (e) {}
    }

    // Inject MapLibre CSS
    try {
      var cssText = b64decode(MAPLIBRE_CSS_B64);
      var styleEl = document.getElementById('maplibre-css-placeholder');
      if (styleEl) styleEl.textContent = cssText;
      postEarly({ type: 'cssInjected', size: cssText.length });
    } catch (e) { postEarly({ type: 'error', msg: 'css inject failed: ' + e.message }); }

    // Inject MapLibre JS bundle
    try {
      var libJs = b64decode(MAPLIBRE_JS_B64);
      (new Function(libJs))();
      // CRITICAL: alias maplibregl as mapboxgl so ShadeMap (which expects
      // mapbox-gl-js) finds the global it needs at construction time.
      if (typeof window.maplibregl !== 'undefined' && !window.mapboxgl) {
        window.mapboxgl = window.maplibregl;
      }
      postEarly({ type: 'maplibreInjected', size: libJs.length, hasGlobal: typeof maplibregl !== 'undefined' });
    } catch (e) { postEarly({ type: 'error', msg: 'maplibre inject failed: ' + e.message }); }

    // Inject ShadeMap UMD
    try {
      var shadeJs = b64decode(SHADEMAP_JS_B64);
      (new Function(shadeJs))();
      postEarly({ type: 'shadeMapInjected', size: shadeJs.length, hasGlobal: typeof ShadeMap !== 'undefined' });
    } catch (e) { postEarly({ type: 'error', msg: 'shadeMap inject failed: ' + e.message }); }
  </script>

  <script>
    var SHADEMAP_KEY = '${SHADEMAP_KEY}';

    // Soleia visual identity
    var SOLEIA_ORANGE = '#F5A623';
    var SOLEIA_GREY = '#9E9E9E';
    var ICONS = {
      bar: String.fromCodePoint(0x1F37A),         // beer mug
      bistro: String.fromCodePoint(0x1F377),      // wine glass
      cafe: String.fromCodePoint(0x2615),          // coffee
      restaurant: String.fromCodePoint(0x1F37D, 0xFE0F), // fork and knife with plate
      rooftop: String.fromCodePoint(0x1F307),     // sunset over buildings
    };
    var FALLBACK_ICON = String.fromCodePoint(0x2600, 0xFE0F); // sun
    // Personalised terrace polygon colors
    var TERRACE_COLORS = {
      garden: '#7CB342',
      pavement: '#F5A623',
      waterfront: '#0288D1',
      frontage: '#FF7043',
      rooftop: '#AB47BC',
      default: '#F5A623'
    };
    var MARKER_MIN_ZOOM = 14;
    var POLYGON_MIN_ZOOM = 16;

    function postToRN(p) {
      try {
        if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
          window.ReactNativeWebView.postMessage(JSON.stringify(p));
        }
      } catch (e) {}
    }

    var map = null;
    var shadeMap = null;
    var markers = []; // [{id, marker, terrace, sunny}]
    var selectedId = null;
    var lastShadeUpdateAt = 0;

    function buildMarkerEl(terrace, sunny) {
      var el = document.createElement('div');
      el.className = 'soleia-marker';
      var color = sunny ? SOLEIA_ORANGE : SOLEIA_GREY;
      el.style.border = '3px solid ' + color;
      el.style.filter = sunny ? 'none' : 'brightness(0.75) saturate(0.6)';
      el.style.opacity = sunny ? '1' : '0.85';
      var iconKey = (terrace.type || 'cafe').toLowerCase();
      var icon = ICONS[iconKey] || FALLBACK_ICON;
      el.textContent = icon;
      el.addEventListener('click', function (ev) {
        ev.stopPropagation();
        postToRN({ type: 'markerPress', id: terrace.id });
      });
      return el;
    }

    function refreshMarkerStyle(entry) {
      if (!entry || !entry.marker) return;
      var el = entry.marker.getElement();
      if (!el) return;
      var color = entry.sunny ? SOLEIA_ORANGE : SOLEIA_GREY;
      el.style.border = '3px solid ' + color;
      el.style.filter = entry.sunny ? 'none' : 'brightness(0.75) saturate(0.6)';
      el.style.opacity = entry.sunny ? '1' : '0.85';
      if (entry.terrace.id === selectedId) el.classList.add('selected');
      else el.classList.remove('selected');
    }

    function clearMarkers() {
      for (var i = 0; i < markers.length; i++) {
        try { markers[i].marker.remove(); } catch (e) {}
      }
      markers = [];
    }

    function applyMarkerVisibility(zoom) {
      var visible = zoom >= MARKER_MIN_ZOOM;
      for (var i = 0; i < markers.length; i++) {
        var el = markers[i].marker.getElement();
        if (el) el.style.display = visible ? 'flex' : 'none';
      }
    }

    function tryUpdateMarkerSun() {
      // Use ShadeMap private profile API to know if a point is in sun.
      // Falls back gracefully if the API is missing or throws.
      if (!shadeMap || typeof shadeMap._generateShadeProfile !== 'function') return null;
      var locs = markers.map(function (m) { return { lng: m.terrace.lng, lat: m.terrace.lat }; });
      if (!locs.length) return null;
      try {
        var pt = shadeMap._generateShadeProfile({
          locations: locs,
          dates: [shadeMap.options ? shadeMap.options.date : new Date()],
          sunColor: [255, 255, 255, 255],
          shadeColor: [0, 0, 0, 255],
        });
        var sunnyCount = 0, shadedCount = 0;
        for (var i = 0; i < markers.length; i++) {
          var inSun = pt[i] === 255 || pt[i * 4] === 255;
          markers[i].sunny = !!inSun;
          refreshMarkerStyle(markers[i]);
          if (markers[i].sunny) sunnyCount++; else shadedCount++;
          postToRN({ type: 'sunUpdate', id: markers[i].terrace.id, sunny: !!inSun });
        }
        return { sunny: sunnyCount, shaded: shadedCount };
      } catch (e) {
        postToRN({ type: 'shadeLog', msg: 'shade profile failed: ' + (e && e.message ? e.message : 'err') });
        return null;
      }
    }

    function initMap() {
      if (typeof maplibregl === 'undefined') {
        postToRN({ type: 'error', msg: 'maplibregl global missing' });
        return;
      }
      // MapTiler Streets - 3D buildings + nice cartography
      var STYLE_URL = 'https://api.maptiler.com/maps/streets/style.json?key=PrVP1L26j30UHcrnm87w';

      map = new maplibregl.Map({
        container: 'map',
        style: STYLE_URL,
        center: [-1.5536, 47.2184], // Nantes default
        zoom: 15,
        minZoom: 3,
        maxZoom: 20,
        pitch: 45,
        bearing: 0,
        attributionControl: false,
        maxPitch: 70,
        antialias: true,
      });

      // Keep zoom + rotate gestures, allow pitch (used for the 3D feel)
      try { map.touchZoomRotate.enable(); } catch (e) {}
      try { map.dragRotate.enable(); } catch (e) {}

      map.on('load', function () {
        postToRN({ type: 'styleLoaded', url: STYLE_URL });
        postToRN({ type: 'mapReady' });

        // Empty source for terrace polygons (populated later via window.updatePolygons)
        if (!map.getSource('soleia-terraces-polygons')) {
          map.addSource('soleia-terraces-polygons', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'soleia-terraces-polygons-fill',
            source: 'soleia-terraces-polygons',
            type: 'fill',
            minzoom: POLYGON_MIN_ZOOM,
            paint: {
              'fill-color': [
                'match', ['get', 'kind'],
                'garden', TERRACE_COLORS.garden,
                'pavement', TERRACE_COLORS.pavement,
                'waterfront', TERRACE_COLORS.waterfront,
                'frontage', TERRACE_COLORS.frontage,
                'rooftop', TERRACE_COLORS.rooftop,
                TERRACE_COLORS.default,
              ],
              'fill-opacity': 0.25,
            },
          });
          map.addLayer({
            id: 'soleia-terraces-polygons-outline',
            source: 'soleia-terraces-polygons',
            type: 'line',
            minzoom: POLYGON_MIN_ZOOM,
            paint: {
              'line-color': [
                'match', ['get', 'kind'],
                'garden', TERRACE_COLORS.garden,
                'pavement', TERRACE_COLORS.pavement,
                'waterfront', TERRACE_COLORS.waterfront,
                'frontage', TERRACE_COLORS.frontage,
                'rooftop', TERRACE_COLORS.rooftop,
                TERRACE_COLORS.default,
              ],
              'line-width': 2,
              'line-dasharray': [3, 1.5],
              'line-opacity': 0.9,
            },
          });
        }

        // ShadeMap init
        try {
          if (typeof ShadeMap !== 'undefined') {
            // Defensive re-alias: in case the earlier alias step ran before
            // window was fully ready, ensure mapboxgl points to maplibregl
            // before constructing ShadeMap.
            if (typeof window.maplibregl !== 'undefined' && !window.mapboxgl) {
              window.mapboxgl = window.maplibregl;
            }
            // Detect local Chrome (file:// protocol) - the MapTiler terrain
            // tiles trigger a CORS / texSubImage2D: no pixels error when
            // loaded from file://. The same code in iOS WebView (which uses
            // baseUrl https://localhost) and on http(s) servers works fine,
            // so we disable terrain ONLY when protocol === 'file:'.
            var IS_LOCAL = (typeof window !== 'undefined') &&
              window.location && window.location.protocol === 'file:';
            var shadeOpts = {
              date: new Date(),
              color: '#01112f',
              opacity: 0.7,
              apiKey: SHADEMAP_KEY,
              belowCanopy: false,
              debug: function (msg) { postToRN({ type: 'shadeLog', msg: String(msg) }); },
            };
            if (!IS_LOCAL) {
              shadeOpts.terrainSource = {
                tileSize: 256,
                maxZoom: 12,
                getSourceUrl: function (args) {
                  return 'https://api.maptiler.com/tiles/terrain-rgb-v2/' +
                    args.z + '/' + args.x + '/' + args.y +
                    '.webp?key=PrVP1L26j30UHcrnm87w';
                },
                getElevation: function (args) {
                  return -10000 + (args.r * 256 * 256 + args.g * 256 + args.b) * 0.1;
                },
              };
            } else {
              postToRN({ type: 'shadeLog', msg: 'IS_LOCAL=true - terrain disabled (file:// CORS)' });
            }
            shadeMap = new ShadeMap(shadeOpts).addTo(map);
            postToRN({ type: 'shadeMapReady', licensed: true, terrain: !IS_LOCAL });

            // When ShadeMap finishes a render pass, update each marker.
            try {
              shadeMap.on && shadeMap.on('idle', function () {
                var now = Date.now();
                if (now - lastShadeUpdateAt < 250) return; // throttle
                lastShadeUpdateAt = now;
                var stats = tryUpdateMarkerSun();
                if (stats) {
                  postToRN({
                    type: 'shadeIdle',
                    sunny: stats.sunny,
                    shaded: stats.shaded,
                    total: stats.sunny + stats.shaded,
                  });
                }
              });
            } catch (e) {}
          } else {
            postToRN({ type: 'error', msg: 'ShadeMap not loaded' });
          }
        } catch (e) {
          postToRN({ type: 'error', msg: 'ShadeMap init failed: ' + (e && e.message ? e.message : String(e)) });
        }
      });

      map.on('error', function (ev) {
        postToRN({ type: 'mapError', msg: ev && ev.error ? String(ev.error.message || ev.error) : 'unknown' });
      });

      map.on('zoomend', function () {
        applyMarkerVisibility(map.getZoom());
      });
    }

    // ----- API exposed to React Native (via injectJavaScript) ----------------

    /** Replace all markers with the given terraces list. */
    window.updateTerraces = function (list) {
      try {
        if (!map) return;
        var arr = Array.isArray(list) ? list : [];
        clearMarkers();
        for (var i = 0; i < arr.length; i++) {
          var t = arr[i];
          if (typeof t.lat !== 'number' || typeof t.lng !== 'number') continue;
          var sunny = t.sun_status === 'sunny';
          var el = buildMarkerEl(t, sunny);
          var m = new maplibregl.Marker({ element: el, anchor: 'center' })
            .setLngLat([t.lng, t.lat])
            .addTo(map);
          markers.push({ id: t.id, marker: m, terrace: t, sunny: sunny });
        }
        applyMarkerVisibility(map.getZoom());
        postToRN({
          type: 'markersAdded',
          count: markers.length,
          zoom: Math.round(map.getZoom() * 10) / 10,
        });
        // Try a first sun pass right away (may noop if shadeMap not ready)
        tryUpdateMarkerSun();
      } catch (e) {
        postToRN({ type: 'error', msg: 'updateTerraces failed: ' + e.message });
      }
    };

    /** Replace the polygon source. Pass a GeoJSON FeatureCollection. */
    window.updatePolygons = function (geojson) {
      try {
        if (!map || !map.getSource('soleia-terraces-polygons')) return;
        map.getSource('soleia-terraces-polygons').setData(
          geojson || { type: 'FeatureCollection', features: [] },
        );
        postToRN({
          type: 'polygonsUpdated',
          count: (geojson && geojson.features ? geojson.features.length : 0),
        });
      } catch (e) {
        postToRN({ type: 'error', msg: 'updatePolygons failed: ' + e.message });
      }
    };

    /** Set ShadeMap simulation date. Accepts ISO string or epoch ms. */
    window.setShadeTime = function (input) {
      try {
        if (!shadeMap) return;
        var d = typeof input === 'number' ? new Date(input) : new Date(String(input));
        if (isNaN(d.getTime())) return;
        shadeMap.setDate(d);
        postToRN({ type: 'shadeLog', msg: 'setDate ' + d.toISOString() });
      } catch (e) {
        postToRN({ type: 'error', msg: 'setShadeTime failed: ' + e.message });
      }
    };

    /** Highlight a specific terrace marker. */
    window.setSelected = function (id) {
      selectedId = id || null;
      for (var i = 0; i < markers.length; i++) refreshMarkerStyle(markers[i]);
    };

    /** Fly the camera to a coordinate. */
    window.flyTo = function (lat, lng, zoom) {
      if (!map) return;
      map.flyTo({ center: [lng, lat], zoom: zoom != null ? zoom : 17, pitch: 45, duration: 800 });
    };

    /** Recenter without animation. */
    window.setCenter = function (lat, lng, zoom) {
      if (!map) return;
      map.jumpTo({ center: [lng, lat], zoom: zoom != null ? zoom : 15 });
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
