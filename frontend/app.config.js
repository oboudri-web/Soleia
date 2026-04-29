// Soleia - Expo dynamic config.
// Wraps app.json and injects the @rnmapbox/maps plugin with the secret
// MAPBOX_DOWNLOAD_TOKEN read from process.env (set in .env locally and
// in EAS env var on the build server). The download token is *only* used
// at prebuild/build time to fetch the iOS/Android Mapbox SDK from Mapbox's
// private artifact registry. It must NEVER be shipped in the JS bundle.

const baseConfig = require('./app.json').expo;

module.exports = ({ config: _ignored }) => {
  const downloadToken =
    process.env.MAPBOX_DOWNLOAD_TOKEN ||
    process.env.RNMAPBOX_MAPS_DOWNLOAD_TOKEN ||
    '';

  const plugins = [
    ...baseConfig.plugins,
    [
      '@rnmapbox/maps',
      {
        // 'mapbox' = use the proprietary Mapbox SDK (better perf + 3D buildings).
        // Alternative 'maplibre' is fully OSS but lacks ShadeMap parity.
        RNMapboxMapsImpl: 'mapbox',
        RNMapboxMapsDownloadToken: downloadToken,
      },
    ],
  ];

  return {
    ...baseConfig,
    plugins,
  };
};
