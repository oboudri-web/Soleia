/**
 * Soleia — Map HTML as JavaScript string.
 *
 * This is the *exact* contents of /app/frontend/assets/map.html, exported as a
 * string so we can pass it to <WebView source={{ html: MAP_HTML }} />.
 *
 * Why not load the .html file directly?
 *   • Metro's default `assetExts` doesn't include 'html'.
 *   • We can't edit metro.config.js (protected).
 *   • A static string is fast to bundle, gzipped well, and works offline.
 *
 * Keep this file in sync with assets/map.html (manually for now).
 */
export const MAP_HTML = `<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <title>Soleia Map</title>
  <link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet" />
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

  <script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
  <script src="https://unpkg.com/mapbox-gl-shadow-simulator@0.13.0/dist/mapbox-gl-shadow-simulator.umd.min.js"></script>

  <script>
    const MAPTILER_KEY = 'PrVP1L26j30UHcrnm87w';
    const SHADEMAP_KEY = 'eyJhbGciOiJIUzI1NiJ9.eyJlbWFpbCI6Im9ib3VkcmlAZ21haWwuY29tIiwiY3JlYXRlZCI6MTc3NzE5NjQ0NzAwMiwiaWF0IjoxNzc3MTk2NDQ3fQ.Mu6MZW3988d8F4OHMuNQzUllI46EZscid0sFTofwW_o';
    const STYLE_URL = 'https://api.maptiler.com/maps/streets/style.json?key=' + MAPTILER_KEY;
    const TERRAIN_URL_TEMPLATE = 'https://api.maptiler.com/tiles/terrain-rgb-v2/{z}/{x}/{y}.webp?key=' + MAPTILER_KEY;

    function postToRN(payload) {
      try {
        if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
          window.ReactNativeWebView.postMessage(JSON.stringify(payload));
        }
      } catch (e) {}
    }

    let map = null;
    let shadeMap = null;
    let terraces = [];
    let viewportPostScheduled = false;

    function initMap(initialCenter, initialZoom) {
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

      map.on('load', () => {
        postToRN({ type: 'mapReady' });
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
            postToRN({ type: 'error', msg: 'ShadeMap library not loaded' });
          }
        } catch (e) {
          postToRN({ type: 'error', msg: 'ShadeMap init failed: ' + (e && e.message ? e.message : String(e)) });
        }
      });

      map.on('error', function (ev) {
        postToRN({ type: 'mapError', msg: ev && ev.error ? String(ev.error.message || ev.error) : 'unknown' });
      });

      const scheduleViewportPost = function () {
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
      const c = map.getCenter();
      const points = terraces
        .filter(function (t) { return typeof t.lat === 'number' && typeof t.lng === 'number'; })
        .map(function (t) {
          const p = map.project([t.lng, t.lat]);
          return {
            id: t.id,
            x: Math.round(p.x),
            y: Math.round(p.y),
            sunny: t.sun_status === 'sunny' ? 1 : 0,
          };
        });
      const b = map.getBounds();
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
        postViewport();
      } catch (e) {
        postToRN({ type: 'error', msg: 'updateTerraces failed: ' + e.message });
      }
    };

    window.setShadeTime = function (input) {
      try {
        if (!shadeMap) return;
        const d = typeof input === 'number' ? new Date(input) : new Date(String(input));
        if (isNaN(d.getTime())) return;
        shadeMap.setDate(d);
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
      initMap();
      postToRN({ type: 'htmlLoaded' });
    });
  </script>
</body>
</html>`;
