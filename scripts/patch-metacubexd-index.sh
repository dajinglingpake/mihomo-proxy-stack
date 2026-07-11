#!/bin/sh
set -eu

html="${METACUBEXD_INDEX_HTML:-/usr/share/nginx/html/index.html}"
cache_bust="${CONFIG_HELPER_CACHE_BUST:-v12672-sub-rows25}"

endpoint_script='<script>window.__METACUBEXD_CONFIG__ = window.__METACUBEXD_CONFIG__ || { defaultBackendURL: "" };!function(){const e="local-backend",t=window.location.origin+"/backend",o=[{id:e,url:t,secret:""}],r=JSON.stringify(o);try{localStorage.removeItem("selectedEndpoint"),localStorage.removeItem("endpointList"),localStorage.setItem("selectedEndpoint",e),localStorage.setItem("endpointList",r),sessionStorage.removeItem("showMagicPathDialog"),sessionStorage.removeItem("skippedConnectionCycle");const n=localStorage.getItem.bind(localStorage),a=localStorage.setItem.bind(localStorage);localStorage.getItem=function(i){return i==="selectedEndpoint"?e:i==="endpointList"?r:n(i)},localStorage.setItem=function(i,l){if(i==="selectedEndpoint")return a(i,e);if(i==="endpointList")return a(i,r);return a(i,l)}}catch(n){console.error("failed to enforce endpoint",n)}window.__METACUBEXD_CONFIG__={defaultBackendURL:t}}();</script>'
helper_script="<script defer src=\"./config-helper.js?v=${cache_bust}\"></script>"
config_script='<script>window.__METACUBEXD_CONFIG__ = window.__METACUBEXD_CONFIG__ || { defaultBackendURL: '"''"' }</script>'

sed -i "s#onerror=\"window.__METACUBEXD_CONFIG__={defaultBackendURL:''}\"#onerror=\"window.__METACUBEXD_CONFIG__={defaultBackendURL:window.location.origin+'/backend'}\"#" "$html"

if ! grep -q "local-backend" "$html"; then
  sed -i "s#${config_script}#${endpoint_script}#" "$html"
fi

if ! grep -q "config-helper.js" "$html"; then
  sed -i "s#</head>#${helper_script}</head>#" "$html"
fi

sed -i 's#defaultBackendURL:""#defaultBackendURL:window.location.origin+"/backend"#g' "$html"
