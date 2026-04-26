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
        // ----- Hide POI / transit / parking / bicycle / ferry / airport
        // and most label layers (keep road labels for street names).
        try {
          var hideKeywords = [
            'poi', 'transit', 'bus', 'tram', 'parking',
            'bicycle', 'airport', 'ferry',
          ];
          // Labels we keep (road labels make street names readable)
          var keepLabelKeywords = ['road-label', 'road_label', 'road-name', 'street'];
          var hiddenCount = 0;
          var styleLayers = (map.getStyle().layers || []);
          for (var iH = 0; iH < styleLayers.length; iH++) {
            var lid = (styleLayers[iH].id || '').toLowerCase();
            var hide = false;
            for (var kH = 0; kH < hideKeywords.length; kH++) {
              if (lid.indexOf(hideKeywords[kH]) !== -1) { hide = true; break; }
            }
            // Also hide any 'label' that is not a road label
            if (!hide && lid.indexOf('label') !== -1) {
              var keep = false;
              for (var kK = 0; kK < keepLabelKeywords.length; kK++) {
                if (lid.indexOf(keepLabelKeywords[kK]) !== -1) { keep = true; break; }
              }
              if (!keep) hide = true;
            }
            if (hide) {
              try { map.setLayoutProperty(styleLayers[iH].id, 'visibility', 'none'); hiddenCount++; }
              catch (eHide) {}
            }
          }
          postToRN({ type: 'layersHidden', count: hiddenCount, total: styleLayers.length });
        } catch (eAll) {
          postToRN({ type: 'error', msg: 'layer hide failed: ' + eAll.message });
        }

        // ----- Terraces source with native Mapbox clustering -----------------
        try {
          map.addSource('soleia-terraces', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
            cluster: true,
            clusterMaxZoom: 15,
            clusterRadius: 50,
            clusterProperties: {
              // sum of 'sunny' (1/0) per child feature - cluster has any sunny if > 0
              sunny: ['+', ['get', 'sunny']],
              soonSunny: ['+', ['get', 'soonSunny']],
            },
          });

          // Cluster bubble (orange if any sunny inside, white if any soonSunny, else grey)
          map.addLayer({
            id: 'soleia-clusters',
            type: 'circle',
            source: 'soleia-terraces',
            filter: ['has', 'point_count'],
            paint: {
              'circle-color': [
                'case',
                ['>', ['get', 'sunny'], 0], '#F5A623',
                ['>', ['get', 'soonSunny'], 0], '#FFFFFF',
                '#9E9E9E',
              ],
              'circle-radius': [
                'step', ['get', 'point_count'],
                14,   // < 5
                5, 18,
                15, 22,
                50, 26,
              ],
              'circle-stroke-width': 2,
              'circle-stroke-color': '#FFFFFF',
              'circle-opacity': 0.95,
            },
          });
          map.addLayer({
            id: 'soleia-cluster-count',
            type: 'symbol',
            source: 'soleia-terraces',
            filter: ['has', 'point_count'],
            layout: {
              'text-field': ['get', 'point_count_abbreviated'],
              'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
              'text-size': 13,
              'text-allow-overlap': true,
            },
            paint: {
              'text-color': [
                'case',
                ['>', ['get', 'sunny'], 0], '#FFFFFF',
                ['>', ['get', 'soonSunny'], 0], '#333333',
                '#FFFFFF',
              ],
            },
          });

          // Unclustered individual marker (8px small dot)
          map.addLayer({
            id: 'soleia-unclustered',
            type: 'circle',
            source: 'soleia-terraces',
            filter: ['!', ['has', 'point_count']],
            paint: {
              'circle-color': [
                'case',
                ['==', ['get', 'sunny'], 1], '#F5A623',
                ['==', ['get', 'soonSunny'], 1], '#FFFFFF',
                '#9E9E9E',
              ],
              'circle-radius': 6,
              'circle-stroke-width': 2,
              'circle-stroke-color': '#FFFFFF',
              'circle-opacity': 0.95,
            },
          });

          // Click cluster -> zoom in
          map.on('click', 'soleia-clusters', function (e) {
            var f = (e.features || [])[0];
            if (!f) return;
            var clusterId = f.properties.cluster_id;
            var src = map.getSource('soleia-terraces');
            if (!src || !src.getClusterExpansionZoom) return;
            src.getClusterExpansionZoom(clusterId, function (err, zoom) {
              if (err) return;
              map.easeTo({ center: f.geometry.coordinates, zoom: zoom });
            });
          });

          // Click individual marker -> postMessage to RN
          map.on('click', 'soleia-unclustered', function (e) {
            var f = (e.features || [])[0];
            if (!f) return;
            postToRN({ type: 'markerPress', id: f.properties.id });
          });

          // Cursor feedback on web (no-op on iOS)
          map.on('mouseenter', 'soleia-clusters', function () { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', 'soleia-clusters', function () { map.getCanvas().style.cursor = ''; });
          map.on('mouseenter', 'soleia-unclustered', function () { map.getCanvas().style.cursor = 'pointer'; });
          map.on('mouseleave', 'soleia-unclustered', function () { map.getCanvas().style.cursor = ''; });
        } catch (eClu) {
          postToRN({ type: 'error', msg: 'cluster setup failed: ' + eClu.message });
        }

        // ----- User location source (blue puck with pulse) ------------------
        try {
          map.addSource('soleia-user', {
            type: 'geojson',
            data: { type: 'FeatureCollection', features: [] },
          });
          map.addLayer({
            id: 'soleia-user-pulse',
            type: 'circle',
            source: 'soleia-user',
            paint: {
              'circle-color': '#4285F4',
              'circle-radius': 18,
              'circle-opacity': 0.18,
              'circle-stroke-width': 0,
            },
          });
          map.addLayer({
            id: 'soleia-user-dot',
            type: 'circle',
            source: 'soleia-user',
            paint: {
              'circle-color': '#4285F4',
              'circle-radius': 7,
              'circle-stroke-width': 2.5,
              'circle-stroke-color': '#FFFFFF',
            },
          });
          // Animate the pulse halo radius (12 -> 24 -> 12) every 1.5s
          var pulseT = 0;
          setInterval(function () {
            try {
              pulseT = (pulseT + 0.05) % (Math.PI * 2);
              var r = 14 + Math.sin(pulseT) * 6;
              map.setPaintProperty('soleia-user-pulse', 'circle-radius', r);
            } catch (eP) {}
          }, 60);
        } catch (eU) {
          postToRN({ type: 'error', msg: 'user dot setup failed: ' + eU.message });
        }

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

      // ── Region change : notifie RN du bbox visible (debounce côté RN) ──
      map.on('moveend', function () {
        try {
          var b = map.getBounds();
          postToRN({
            type: 'regionChange',
            lat_min: b.getSouth(),
            lat_max: b.getNorth(),
            lng_min: b.getWest(),
            lng_max: b.getEast(),
            zoom: map.getZoom(),
          });
        } catch (eRC) {}
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

    /** Push the terraces list to the clustered GeoJSON source. */
    window.updateTerraces = function (list) {
      try {
        if (!map || !map.getSource('soleia-terraces')) return;
        var arr = Array.isArray(list) ? list : [];
        var feats = [];
        for (var i = 0; i < arr.length; i++) {
          var t = arr[i];
          if (typeof t.lat !== 'number' || typeof t.lng !== 'number') continue;
          var sunny = t.sun_status === 'sunny' ? 1 : 0;
          var soonSunny = (t.sun_status === 'soon_sunny' || t.upcoming_sunny) ? 1 : 0;
          feats.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [t.lng, t.lat] },
            properties: {
              id: t.id,
              name: t.name,
              sunny: sunny,
              soonSunny: soonSunny,
              type: t.type || 'cafe',
            },
          });
        }
        map.getSource('soleia-terraces').setData({
          type: 'FeatureCollection',
          features: feats,
        });
        postToRN({ type: 'terracesAck', count: feats.length });
      } catch (e) {
        postToRN({ type: 'error', msg: 'updateTerraces failed: ' + e.message });
      }
    };

    /** Set the user-location blue puck (pulsing halo). Pass null to clear. */
    window.setUserLocation = function (lat, lng, opts) {
      try {
        if (!map || !map.getSource('soleia-user')) return;
        if (typeof lat !== 'number' || typeof lng !== 'number') {
          map.getSource('soleia-user').setData({ type: 'FeatureCollection', features: [] });
          return;
        }
        map.getSource('soleia-user').setData({
          type: 'FeatureCollection',
          features: [{
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [lng, lat] },
            properties: {},
          }],
        });
        if (opts && opts.recenter) {
          map.jumpTo({
            center: [lng, lat],
            zoom: typeof opts.zoom === 'number' ? opts.zoom : 15,
          });
        }
        postToRN({ type: 'userLocationSet', lat: lat, lng: lng });
      } catch (e) {
        postToRN({ type: 'error', msg: 'setUserLocation failed: ' + e.message });
      }
    };

    /** Convenience: update the markers' sun_status without rebuilding all features. */
    window.updateSunStatus = function (updates) {
      try {
        if (!map || !map.getSource('soleia-terraces') || !Array.isArray(updates)) return;
        var current = map.getSource('soleia-terraces')._data;
        if (!current || !current.features) return;
        var byId = {};
        for (var u = 0; u < updates.length; u++) byId[updates[u].id] = updates[u];
        var changed = 0;
        for (var i = 0; i < current.features.length; i++) {
          var f = current.features[i];
          var up = byId[f.properties && f.properties.id];
          if (!up) continue;
          var newSunny = up.sun_status === 'sunny' ? 1 : 0;
          var newSoon = (up.sun_status === 'soon_sunny' || up.upcoming_sunny) ? 1 : 0;
          if (f.properties.sunny !== newSunny || f.properties.soonSunny !== newSoon) {
            f.properties.sunny = newSunny;
            f.properties.soonSunny = newSoon;
            changed++;
          }
        }
        if (changed > 0) map.getSource('soleia-terraces').setData(current);
      } catch (e) {
        postToRN({ type: 'error', msg: 'updateSunStatus failed: ' + e.message });
      }
    };

    document.addEventListener('DOMContentLoaded', function () {
      try { init(); postToRN({ type: 'htmlLoaded' }); }
      catch (e) { postToRN({ type: 'error', msg: 'init threw: ' + e.message }); }
    });
  </script>
</body>
</html>`;
