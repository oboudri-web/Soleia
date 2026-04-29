/* eslint-disable */
/**
 * Soleia map HTML (Mapbox GL JS + ShadeMap) — VERSION SIMPLIFIÉE.
 *
 * Architecture (post-revert PR A) :
 *   - Mapbox GL JS sert la carte de fond avec le style Streets v12
 *   - On garde UNIQUEMENT les POI natifs de classe `food_and_drink`
 *     (restaurants, bars, cafés, brasseries, etc.) — tout le reste
 *     (transit, parking, parks, hôtels, hôpitaux, magasins, etc.) est
 *     masqué pour ne pas polluer la carte
 *   - ShadeMap calcule les ombres en temps réel par-dessus
 *   - Notre BDD de terrasses scrappées s'affiche dans la bottom-sheet
 *     (et plus du tout sur la carte) — c'est notre valeur ajoutée
 *
 * Plus de markers custom = plus de bugs d'affichage iOS.
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
        // ───────────────────────────────────────────────────────────────────
        // POI cleanup : on garde UNIQUEMENT food_and_drink, on masque tout
        // le reste (transit, parking, parks, lodging, shops, etc.).
        //
        // Mapbox Streets v12 organise tous ses POI dans des layers dont
        // l'id contient "poi" (poi-label, poi-label-other, etc.) avec la
        // propriété `class` qui vaut entre autres :
        //   food_and_drink            <- on garde
        //   food_and_drink_stores     <- on supprime (épiceries, marchés)
        //   transit / airport / ferry <- déjà masqués via id-keyword
        //   lodging / commercial_services / sport_and_leisure / park_like
        //   medical / education / religion / etc.
        //
        // Stratégie :
        //   1) Pour chaque layer dont l'id contient "poi" => setFilter pour
        //      ne garder que les features où class == 'food_and_drink'.
        //   2) Hide layers transit/parking/airport/ferry/bicycle (inchangé).
        //   3) Hide tous les autres "label" non-routes (inchangé).
        // ───────────────────────────────────────────────────────────────────
        try {
          var hideKeywords = [
            'transit', 'bus', 'tram', 'parking',
            'bicycle', 'airport', 'ferry',
          ];
          var keepLabelKeywords = ['road-label', 'road_label', 'road-name', 'street'];
          var hiddenCount = 0;
          var poiFiltered = 0;
          var styleLayers = (map.getStyle().layers || []);

          for (var iH = 0; iH < styleLayers.length; iH++) {
            var lid = (styleLayers[iH].id || '').toLowerCase();

            // ── A) POI layers : on filtre sur food_and_drink uniquement
            if (lid.indexOf('poi') !== -1) {
              try {
                map.setFilter(styleLayers[iH].id, [
                  '==', ['get', 'class'], 'food_and_drink'
                ]);
                map.setLayoutProperty(styleLayers[iH].id, 'visibility', 'visible');
                poiFiltered++;
              } catch (eFilter) {
                // some symbol layers don't accept setFilter => hide them silently
                try { map.setLayoutProperty(styleLayers[iH].id, 'visibility', 'none'); } catch (e2) {}
              }
              continue;
            }

            // ── B) Transit/parking/airport/ferry/bicycle : masqués
            var hide = false;
            for (var kH = 0; kH < hideKeywords.length; kH++) {
              if (lid.indexOf(hideKeywords[kH]) !== -1) { hide = true; break; }
            }
            // ── C) Autres "label" non-route : masqués
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
          postToRN({
            type: 'layersHidden',
            count: hiddenCount,
            poiFiltered: poiFiltered,
            total: styleLayers.length,
          });
        } catch (eAll) {
          postToRN({ type: 'error', msg: 'layer setup failed: ' + eAll.message });
        }

        // ───────────────────────────────────────────────────────────────────
        // User location source (blue pulsing dot)
        // ───────────────────────────────────────────────────────────────────
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

        // ───────────────────────────────────────────────────────────────────
        // ShadeMap overlay
        // ───────────────────────────────────────────────────────────────────
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

        // ───────────────────────────────────────────────────────────────────
        // POI tap → relayer vers RN avec le nom (si l'utilisateur clique
        // sur un bar/resto Mapbox, on ouvre éventuellement la carte côté RN).
        // ───────────────────────────────────────────────────────────────────
        try {
          map.on('click', function (e) {
            var feats = map.queryRenderedFeatures(e.point, {
              filter: ['==', ['get', 'class'], 'food_and_drink'],
            });
            if (!feats || !feats.length) return;
            var f = feats[0];
            var p = f.properties || {};
            postToRN({
              type: 'poiPress',
              name: p.name || p.name_fr || p.name_en || '',
              maki: p.maki || '',
              lng: f.geometry && f.geometry.coordinates ? f.geometry.coordinates[0] : null,
              lat: f.geometry && f.geometry.coordinates ? f.geometry.coordinates[1] : null,
            });
          });
        } catch (ePoi) {
          postToRN({ type: 'error', msg: 'poi click setup failed: ' + ePoi.message });
        }

        postToRN({ type: 'mapReady' });
      });

      map.on('error', function (ev) {
        postToRN({ type: 'mapError', msg: ev && ev.error ? String(ev.error.message || ev.error) : 'unknown' });
      });

      // ── Region change : on notifie RN du bbox visible (debounce côté RN) ──
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

    // ───────────────────────────────────────────────────────────────────────
    // Bridge functions exposed to React Native
    // ───────────────────────────────────────────────────────────────────────

    /** Set ShadeMap simulation date. Accepts ISO string or epoch ms. */
    window.setShadeTime = function (input) {
      try {
        if (!shadeMap) return;
        var d = typeof input === 'number' ? new Date(input) : new Date(String(input));
        if (isNaN(d.getTime())) return;
        nowDate = d;
        shadeMap.setDate(d);
        var localStr;
        try {
          localStr = d.toLocaleString('fr-FR', { timeZone: 'Europe/Paris', hour: '2-digit',
            minute: '2-digit', day: '2-digit', month: '2-digit', year: 'numeric' });
        } catch (eFmt) { localStr = d.toString(); }
        postToRN({ type: 'shadeLog', msg: 'setDate iso=' + d.toISOString() + ' paris=' + localStr });
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

    /**
     * No-op kept for RN parent compat. The terrace list is no longer
     * rendered on the map (only in the bottom sheet). Custom markers
     * have been removed to eliminate iOS rendering bugs.
     */
    window.updateTerraces = function (_list) {
      try {
        var n = Array.isArray(_list) ? _list.length : 0;
        // Acknowledge so the RN debug overlay does not stay at "rnSent>0,rendered=0".
        postToRN({ type: 'terracesReceived', count: n });
        postToRN({ type: 'terracesAck', count: 0 });
      } catch (e) {}
    };

    /** No-op kept for RN parent compat. Selected state is handled in RN. */
    window.setSelected = function (_id) { /* no-op */ };

    /** No-op kept for RN parent compat. Polygons removed. */
    window.updatePolygons = function (_geojson) { /* no-op */ };

    /** No-op kept for RN parent compat. Sun status updates removed. */
    window.updateSunStatus = function (_updates) { /* no-op */ };

    document.addEventListener('DOMContentLoaded', function () {
      try { init(); postToRN({ type: 'htmlLoaded' }); }
      catch (e) { postToRN({ type: 'error', msg: 'init threw: ' + e.message }); }
    });
  </script>
</body>
</html>`;
