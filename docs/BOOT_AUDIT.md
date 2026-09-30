# Nokido Boot Audit - 2026-05-02 19:55

## Vue ensemble

| Source | Count |
|---|---|
| Services auto-start | 112 |
| Scheduled tasks (logon/boot) | 41 |
| Registry Run keys | 12 |
| Startup folders | 5 |
| Drivers boot/system | 85 |

## Services par categorie

### Hardware-Vendor (5)

| Name | Display | Status |
|---|---|---|
| AMD Crash Defender Service | AMD Crash Defender Service | Running |
| AMD External Events Utility | AMD External Events Utility | Running |
| AmdPpkgSvc | AMD Provisioning Packages Service | Running |
| BITS | Service de transfert intelligent en arrière-plan | Running |
| RtkAudioUniversalService | Realtek Audio Universal Service | Running |

### Nokido (12)

| Name | Display | Status |
|---|---|---|
| NokidoAutonomousLoops | Nokido Autonomous Loops (free local LLMs) | Running |
| NokidoDenoHubMCP | Nokido Deno Hub MCP :8769 | Running |
| NokidoDenoProxy | Nokido Deno Proxy nervous system :8000 | Running |
| NokidoDenoWebHub | Nokido Deno WebHub :7401 | Running |
| NokidoGeminiDaemon | NokidoGeminiDaemon | Running |
| NokidoGraph | NokidoGraph | Running |
| NokidoHebbian | NokidoHebbian | Running |
| NokidoHomeostasis | NokidoHomeostasis | Running |
| NokidoLlamaRouter | NokidoLlamaRouter | Running |
| LaForgeMCP | LaForgeMCP | Stopped |
| NokidoRSSWatcher | NokidoRSSWatcher | Running |
| NokidoWebHub | NokidoWebHub | Running |

### Network (3)

| Name | Display | Status |
|---|---|---|
| agent_ovpnconnect | OpenVPN Agent agent_ovpnconnect | Running |
| ovpnhelper_service | OpenVPN Connect Helper Service | Running |
| PureVPN Service | PureVPN Service | Running |

### Third-Party (60)

| Name | Display | Status |
|---|---|---|
| AppXSvc | Service de déploiement AppX (AppXSVC) | Running |
| ArmouryCrateService | Armoury Crate Service | Running |
| asComSvc | ASUS Com Service | Running |
| asus | Service ASUS Update (asus) | Stopped |
| AsusCertService | ASUS Certificate Service | Running |
| AsusFanControlService | AsusFanControlService | Running |
| AsusROGLSLService | AsusROGLSLService Download ROGLSLoader | Stopped |
| AsusUpdateCheck | AsusUpdateCheck | Running |
| BFE | Moteur de filtrage de base | Running |
| BrokerInfrastructure | Service d’infrastructure des tâches en arrière-plan | Running |
| camsvc | Service Gestionnaire d’accès aux fonctionnalités | Running |
| cbdhsvc_dc8b97 | Service utilisateur du Presse-papiers_dc8b97 | Running |
| CDPSvc | Service de plateforme des appareils connectés | Running |
| CDPUserSvc_dc8b97 | Service pour utilisateur de plateforme d’appareils connectés_dc8b97 | Running |
| CmService | Service du gestionnaire de conteneurs | Running |
| CoreMessagingRegistrar | CoreMessaging | Running |
| CoworkVMService | Claude | Running |
| CryptSvc | Services de chiffrement | Running |
| DeviceAssociationService | Service d’association de périphérique | Running |
| DiagTrack | Expériences des utilisateurs connectés et télémétrie | Running |
| DispBrokerDesktopSvc | Service de stratégie d'affichage | Running |
| DPS | Service de stratégie de diagnostic | Running |
| DriversCloudAgent | DriversCloud Agent | Stopped |
| DusmSvc | Consommation des données | Running |
| EventSystem | Système d’événement COM+ | Running |
| GoogleUpdaterInternalService148.0.7730.0 | Service interne de mise à jour Google (GoogleUpdaterInternalService148.0.7730.0) | Stopped |
| GoogleUpdaterService148.0.7730.0 | Service de mise à jour Google (GoogleUpdaterService148.0.7730.0) | Stopped |
| gpsvc | Client de stratégie de groupe | Running |
| IKEEXT | Modules de génération de clés IKE et AuthIP | Running |
| InventorySvc | Service d’Appraisal inventaire et compatibilité | Running |
| iphlpsvc | Assistance IP | Running |
| MapsBroker | Gestionnaire des cartes téléchargées | Stopped |
| nsi | Service Interface du magasin réseau | Running |
| OneSyncSvc_dc8b97 | Hôte de synchronisation_dc8b97 | Running |
| PasswordManagerSDKService | PasswordManagerSDKService | Running |
| PcaSvc | Service de l’Assistant Compatibilité des programmes | Running |
| ProfSvc | Service de profil utilisateur | Running |
| RasMan | Gestionnaire des connexions d’accès à distance | Running |
| Razer Update Service | Razer Update Service | Running |
| ROG Live Service | ROG Live Service | Running |
| RpcEptMapper | Mappeur de point de terminaison RPC | Running |
| RunSwUSB | RunSwUSB | Running |
| RzSndSrv | RzSndSrv | Running |
| SamSs | Gestionnaire de comptes de sécurité | Running |
| SENS | Service de notification d’événements système | Running |
| ShellHWDetection | Détection matériel noyau | Running |
| sppsvc | Protection logicielle | Stopped |
| ssh-agent | OpenSSH Authentication Agent | Running |
| StateRepository | Service State Repository (StateRepository) | Running |
| StorSvc | Service de stockage | Running |
| SystemEventsBroker | Service Broker des événements système | Running |
| TextInputManagementService | Service de gestion des entrées de texte | Running |
| TrkWks | Client de suivi de lien distribué | Running |
| usbipd | USBIP Device Host | Running |
| vmms | Gestion d’ordinateurs virtuels Hyper-V | Running |
| VSS | Cliché instantané des volumes | Stopped |
| webthreatdefusersvc_dc8b97 | Service d’utilisateur Web Threat Defense_dc8b97 | Running |
| WSAIFabricSvc | WSAIFabricSvc | Running |
| wscsvc | Centre de sécurité | Running |
| WSLService | WSL Service | Running |

### Windows-Core (32)

| Name | Display | Status |
|---|---|---|
| AudioEndpointBuilder | Générateur de points de terminaison du service Audio Windows | Running |
| Audiosrv | Audio Windows | Running |
| ClickToRunSvc | Microsoft Office Click-to-Run Service | Running |
| DcomLaunch | Lanceur de processus serveur DCOM | Running |
| Dhcp | Client DHCP | Running |
| Dnscache | Client DNS | Running |
| edgeupdate | Microsoft Edge Update Service (edgeupdate) | Stopped |
| EventLog | Journal d’événements Windows | Running |
| fhsvc | Service d’historique des fichiers | Running |
| FontCache | Service de cache de police Windows | Running |
| LanmanServer | Serveur | Running |
| LanmanWorkstation | Station de travail | Running |
| LSM | Gestionnaire de session locale | Running |
| MDCoreSvc | Microsoft Defender Service de base | Running |
| mpssvc | Pare-feu Windows Defender | Running |
| Power | Alimentation | Running |
| RpcSs | Appel de procédure distante (RPC) | Running |
| Schedule | Planificateur de tâches | Running |
| Spooler | Spouleur d’impression | Running |
| StiSvc | Acquisition d’image Windows (WIA) | Stopped |
| Themes | Thèmes | Running |
| UserManager | Gestionnaire des utilisateurs | Running |
| W32Time | Temps Windows | Running |
| Wcmsvc | Gestionnaire des connexions Windows | Running |
| whesvc | Intégrité de Windows et expériences optimisées | Running |
| WinDefend | Service antivirus Microsoft Defender | Running |
| Winmgmt | Infrastructure de gestion Windows | Running |
| WinRM | Gestion à distance de Windows (Gestion WSM) | Running |
| WlanSvc | Service de configuration automatique WLAN | Running |
| WpnService | Service du système de notifications Push Windows | Running |
| WpnUserService_dc8b97 | Service utilisateur de notifications Push Windows_dc8b97 | Running |
| WSearch | Windows Search | Running |

## Scheduled tasks (boot + logon)

| Task | Path | State | Execute |
|---|---|---|---|
| OneDrive Startup Task-S-1-5-21-XXXX | \ | Ready | C:\Program Files\Microsoft OneDrive\26.062.0402.0002\OneDriv |
| StartCN | \ | Ready | "C:\Program Files\AMD\CNext\CNext\cncmd.exe" |
| StartDVR | \ | Ready | "C:\Program Files\AMD\CNext\CNext\RSServCmd.exe" |
| AcPowerNotification | \ASUS\ | Running | C:\Program Files (x86)\ASUS\ArmouryDevice\dll\AcPowerNotific |
| ArmourySocketServer | \ASUS\ | Ready | C:\Program Files (x86)\ASUS\ArmouryDevice\dll\ArmourySocketS |
| NoiseCancelingEngine | \ASUS\ | Ready | C:\Program Files (x86)\ASUS\ArmouryDevice\dll\MBLedSDK\Noise |
| P508PowerAgent_sdk | \ASUS\ | Ready | C:\Program Files (x86)\ASUS\ArmouryDevice\dll\ShareFromArmou |
| Office Actions Server | \Microsoft\Office\ | Ready | C:\Program Files\Microsoft Office\root\VFS\ProgramFilesCommo |
| Office Automatic Updates 2.0 | \Microsoft\Office\ | Ready | C:\Program Files\Common Files\Microsoft Shared\ClickToRun\Of |
| Office Background Push Maintenance | \Microsoft\Office\ | Ready | C:\Program Files\Microsoft Office\root\vfs\ProgramFilesCommo |
| Office Feature Updates Logon | \Microsoft\Office\ | Ready | C:\Program Files\Microsoft Office\root\Office16\sdxhelper.ex |
| Office Startup Maintenance | \Microsoft\Office\ | Ready | C:\Program Files\Microsoft Office\root\VFS\ProgramFilesCommo |
| AD RMS Rights Policy Template Management (Manual) | \Microsoft\Windows\Active Directory Rights Management Services Client\ | Ready |  |
| Proxy | \Microsoft\Windows\Autochk\ | Ready | %windir%\system32\rundll32.exe |
| UserTask | \Microsoft\Windows\CertificateServicesClient\ | Ready |  |
| ClipESUConsumer | \Microsoft\Windows\Clip\ | Ready | %SystemRoot%\system32\ClipESUConsumer.exe |
| Data Integrity Check And Scan | \Microsoft\Windows\Data Integrity Scan\ | Ready |  |
| Device User | \Microsoft\Windows\Device Information\ | Ready | %windir%\system32\devicecensus.exe |
| RecommendedTroubleshootingScanner | \Microsoft\Windows\Diagnosis\ | Ready |  |
| DirectXDatabaseUpdater | \Microsoft\Windows\DirectX\ | Ready | %windir%\system32\directxdatabaseupdater.exe |
| DXGIAdapterCache | \Microsoft\Windows\DirectX\ | Ready | %windir%\system32\dxgiadaptercache.exe |
| ExploitGuard MDM policy Refresh | \Microsoft\Windows\ExploitGuard\ | Ready |  |
| Monitoring | \Microsoft\Windows\Hotpatch\ | Ready | %systemroot%\system32\cmd.exe |
| Synchronize Language Settings | \Microsoft\Windows\International\ | Ready |  |
| Installation | \Microsoft\Windows\LanguageComponentsInstaller\ | Ready |  |
| ReconcileLanguageResources | \Microsoft\Windows\LanguageComponentsInstaller\ | Ready |  |
| Logon | \Microsoft\Windows\Management\Provisioning\ | Ready | %windir%\system32\ProvTool.exe |
| AutomaticOfflineMemoryDiagnostic | \Microsoft\Windows\MemoryDiagnostic\ | Ready |  |
| SystemSoundsService | \Microsoft\Windows\Multimedia\ | Running |  |
| NcsiIdentifyUserProxies | \Microsoft\Windows\Network Connectivity Status Indicator\ | Ready |  |
| Device Install Reboot Required | \Microsoft\Windows\Plug and Play\ | Ready |  |
| PITRTask | \Microsoft\Windows\Setup\ | Ready |  |
| SpaceAgentTask | \Microsoft\Windows\SpacePort\ | Ready | %windir%\system32\SpaceAgent.exe |
| SpaceManagerTask | \Microsoft\Windows\SpacePort\ | Ready | %windir%\system32\spaceman.exe |
| MsCtfMonitor | \Microsoft\Windows\TextServicesFramework\ | Ready |  |
| QueueReporting | \Microsoft\Windows\Windows Error Reporting\ | Ready | %windir%\system32\wermgr.exe |
| Calibration Loader | \Microsoft\Windows\WindowsColorSystem\ | Ready |  |
| PLUGScheduler | \Microsoft\Windows\WindowsUpdate\RUXIM\ | Ready | "%ProgramFiles%\RUXIM\PLUGscheduler.exe" |
| CacheTask | \Microsoft\Windows\Wininet\ | Running |  |
| Work Folders Logon Synchronization | \Microsoft\Windows\Work Folders\ | Ready |  |
| Work Folders Maintenance Work | \Microsoft\Windows\Work Folders\ | Ready |  |

## Registry Run keys

| Hive | Key | Name | Value |
|---|---|---|---|
| HKCU | Run | Ditto | C:\Program Files\Ditto\Ditto.exe |
| HKCU | Run | Docker Desktop | C:\Program Files\Docker\Docker\Docker Desktop.exe |
| HKCU | Run | electron.app.Notion | "~\AppData\Local\Programs\Notion\Notion.exe" --open-at-login |
| HKCU | Run | Free Download Manager | "C:\Program Files\Softdeluxe\Free Download Manager\fdm.exe" --hidden |
| HKCU | Run | Mozilla-Firefox-308046B0AF4A39CB | "C:\Program Files\Mozilla Firefox\firefox.exe" -os-autostart |
| HKCU | Run | OneDrive | "C:\Program Files\Microsoft OneDrive\OneDrive.exe" /background |
| HKCU | Run | org.openvpn.client | C:\Program Files\OpenVPN Connect\OpenVPNConnect.exe --opened-at-login --minimize |
| HKCU | Run | RzAppEngine | "C:\Program Files\Razer\RzAppEngine\rzappengine.exe" --start-hidden --url-params |
| HKLM | RunOnce | msedge_cleanup_{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5} | "C:\Program Files (x86)\Microsoft\EdgeWebView\Application\147.0.3912.98\Installe |
| HKLM | Run | RtkAudUService | "C:\WINDOWS\System32\DriverStore\FileRepository\realtekservice.inf_amd64_2c6939f |
| HKLM | Run | RZSurroundHelper | C:\WINDOWS\system32\RZSurroundHelper.exe |
| HKLM | Run | SecurityHealth | C:\WINDOWS\system32\SecurityHealthSystray.exe |

## Startup folders

- **PerUser** : ADB WiFi Connector.lnk
- **PerUser** : desktop.ini
- **PerUser** : netcfg-agent-mcp.cmd
- **PerUser** : Ollama.lnk
- **PerUser** : desktop.ini

## Drivers boot/system (running)
Total : 85 drivers actifs au boot

