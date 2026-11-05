/**
 * Every place the UI offers help, as `Page#anchor` of the user manual (docs/manual = the wiki).
 * manual.test.ts fails when one of these sections is missing, so renaming a manual heading
 * means updating it here.
 */
export const HELP = {
  // Dashboard
  headline: 'Dashboard#headline',
  airMap: 'Dashboard#air-map',
  routerCards: 'Dashboard#router-cards',
  attention: 'Dashboard#needs-attention',
  routerList: 'Dashboard#router-list',
  routerOverview: 'Dashboard#router-overview',
  // Add router
  addRouter: 'First-router',
  stepAddress: 'First-router#1-where-is-the-router',
  stepHostKey: 'First-router#2-check-the-router-is-the-one-you-mean',
  stepLogin: 'First-router#3-log-in-to-the-router',
  stepInstallKey: 'First-router#4-install-the-apps-key',
  stepIdentify: 'First-router#5-what-is-this-router-and-its-sockets',
  skipKey: 'First-router#afterwards',
  // Wi-Fi
  wifi: 'Wi-Fi',
  wifiRadios: 'Wi-Fi#radio-tabs',
  wifiModes: 'Wi-Fi#modes',
  wifiChannels: 'Wi-Fi#channels',
  wifiTxPower: 'Wi-Fi#tx-power',
  wifiSecurity: 'Wi-Fi#ssid-and-security',
  wifiApply: 'Wi-Fi#apply-and-proof-on-air',
  wifiMask: 'Wi-Fi#tx-mask-after-a-reload',
  wifiStations: 'Wi-Fi#stations',
  wifiWho: 'Wi-Fi#who-may-join',
  wifiOptions: 'Wi-Fi#all-options',
  // RF live
  rf: 'RF-live',
  rfRadio: 'RF-live#radio',
  rfRx: 'RF-live#rx-at-ap',
  rfTx: 'RF-live#tx-from-ap',
  rfCharts: 'RF-live#charts',
  rfRates: 'RF-live#which-rates-reach-the-station',
  rfRecord: 'RF-live#record-to-csv',
  // LuCI pages
  luci: 'LuCI-pages',
  luciWhich: 'LuCI-pages#which-pages-open-here',
  luciOpen: 'LuCI-pages#opening-a-page',
  luciReadOnly: 'LuCI-pages#read-only-during-a-run',
  luciChanged: 'LuCI-pages#changed-via-luci',
  luciSession: 'LuCI-pages#session-end',
  // Bench Guard
  guardBanner: 'Bench-Guard#what-you-see',
  readOnlyRun: 'Bench-Guard#what-still-works-during-a-run',
  // Terminal and audit log
  terminal: 'Terminal-and-audit-log#terminal',
  auditLog: 'Terminal-and-audit-log#audit-log',
  // Settings
  settings: 'Settings',
  updates: 'Settings#updates',
  checkUpdates: 'Updating#when-it-checks',
  installUpdate: 'Updating#installing-an-update',
  reinstallPrevious: 'Updating#going-back',
  appearance: 'Settings#appearance',
  folders: 'Settings#folders',
  watchList: 'Settings#bench-guard',
  appKey: 'Settings#app-ssh-key',
  retention: 'Settings#audit-log',
  about: 'Settings#about',
} as const
