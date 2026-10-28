/* [Pikmin 4] The online and system-applet services a game reaches through the SDK, answered as an offline PC:
 * no network (nifm, socket, nsd, ssl, bcat), no play reports (prepo: accepted and dropped), no shop / web / software
 * keyboard applets (they return "cancelled"), no local wireless (ldn), and a profanity filter that finds nothing.
 * Without these the SDK's own versions open services (nifm:u, bsd:u, bcat:u, prepo:u, ...) the host does not serve.
 * Results: module 110 (nifm), 122 (bcat), 129 (prepo), 166 (web/applet), 203 (ldn), 123 (ssl) "not available". */
#include <stdio.h>
#include <string.h>

#include "host.h"
#include "../runtime/hle.h"

#define RESULT(module, desc) ((uint32_t)(module) | ((uint32_t)(desc) << 9))
#define R_NIFM_OFFLINE RESULT(110, 3400)   /* network not available */
#define R_BCAT_UNAVAILABLE RESULT(122, 1)
#define R_APPLET_CANCELLED RESULT(128, 140)
#define R_SSL_UNAVAILABLE RESULT(123, 1)
#define R_NSD_UNAVAILABLE RESULT(141, 1)
#define BSD_ENETDOWN 50

static void none(void) {}
static uint32_t ok(void) { return 0; }
static unsigned char no(void) { return 0; }

/* ---- nifm: never connected */
static uint32_t nifm_offline(void) { return R_NIFM_OFFLINE; }
static uint32_t nifm_proxy(void *out) { if (out) memset(out, 0, 0xAA); return R_NIFM_OFFLINE; }
HLE_NATIVE("_ZN2nn4nifm10InitializeEv", ok, 'w')
HLE_NATIVE("_ZN2nn4nifm18IsNetworkAvailableEv", no, 'b')
HLE_NATIVE("_ZN2nn4nifm22IsNetworkRequestOnHoldEv", no, 'b')
HLE_NATIVE("_ZN2nn4nifm20SubmitNetworkRequestEv", none, 'v')
HLE_NATIVE("_ZN2nn4nifm27SubmitNetworkRequestAndWaitEv", none, 'v')
HLE_NATIVE("_ZN2nn4nifm20CancelNetworkRequestEv", none, 'v')
HLE_NATIVE("_ZN2nn4nifm31HandleNetworkRequestErrorResultEv", nifm_offline, 'w')
HLE_NATIVE("_ZN2nn4nifm22GetCurrentProxySettingEPNS0_12ProxySettingE", nifm_proxy, 'w')

/* ---- socket: initialises, every socket call fails with ENETDOWN; the byte-order helpers are real */
static int sock_fail(void) { return -1; }
static int sock_errno(void) { return BSD_ENETDOWN; }
static uint32_t htonl32(uint32_t v) { return __builtin_bswap32(v); }
static uint32_t htons16(uint32_t v) { return __builtin_bswap16((uint16_t)v); }
static int sock_pton(int af, const char *src, uint8_t *dst) {   /* AF_INET only: dotted quad */
    unsigned a, b, c, d;
    if (af != 2 || !src || !dst || sscanf(src, "%u.%u.%u.%u", &a, &b, &c, &d) != 4 || a > 255 || b > 255 || c > 255 || d > 255)
        return 0;
    dst[0] = (uint8_t)a; dst[1] = (uint8_t)b; dst[2] = (uint8_t)c; dst[3] = (uint8_t)d;
    return 1;
}
static int sock_addrinfo(const char *n, const char *s, const void *h, void **res) { (void)n; (void)s; (void)h; if (res) *res = NULL; return -2; }   /* EAI_NONAME */
HLE_NATIVE("_ZN2nn6socket10InitializeEPvmmi", ok, 'w')
HLE_NATIVE("_ZN2nn6socket6SocketEiii", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket4BindEiPK8sockaddrj", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket7ConnectEiPK8sockaddrj", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket6ListenEii", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket6AcceptEiP8sockaddrPj", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket4RecvEiPvmi", sock_fail, 'x')
HLE_NATIVE("_ZN2nn6socket8RecvFromEiPvmiP8sockaddrPj", sock_fail, 'x')
HLE_NATIVE("_ZN2nn6socket4SendEiPKvmi", sock_fail, 'x')
HLE_NATIVE("_ZN2nn6socket6SendToEiPKvmiPK8sockaddrj", sock_fail, 'x')
HLE_NATIVE("_ZN2nn6socket5CloseEi", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket8ShutdownEii", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket10GetSockOptEiiiPvPj", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket10SetSockOptEiiiPKvj", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket11GetPeerNameEiP8sockaddrPj", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket11GetSockNameEiP8sockaddrPj", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket4PollEP6pollfdmi", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket6SelectEiP6fd_setS2_S2_P7timeval", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket5FcntlEiiz", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket5IoctlEijPvm", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket11GetAddrInfoEPKcS2_PK8addrinfoPPS3_", sock_addrinfo, 'w')
HLE_NATIVE("_ZN2nn6socket12FreeAddrInfoEP8addrinfo", none, 'v')
HLE_NATIVE("_ZN2nn6socket11GetNameInfoEPK8sockaddrjPcjS4_ji", sock_fail, 'w')
HLE_NATIVE("_ZN2nn6socket12GetLastErrnoEv", sock_errno, 'w')
HLE_NATIVE("_ZN2nn6socket12GetLastErrorEv", sock_errno, 'w')
HLE_NATIVE("_ZN2nn6socket8InetPtonEiPKcPv", sock_pton, 'w')
HLE_NATIVE("_ZN2nn6socket9InetHtonlEj", htonl32, 'w')
HLE_NATIVE("_ZN2nn6socket9InetNtohlEj", htonl32, 'w')
HLE_NATIVE("_ZN2nn6socket9InetHtonsEt", htons16, 'w')
HLE_NATIVE("_ZN2nn6socket9InetNtohsEt", htons16, 'w')

/* ---- nsd / ssl: no name resolution, no TLS */
static uint32_t nsd_fail(void *out, const void *in) { (void)out; (void)in; return R_NSD_UNAVAILABLE; }
static uint32_t ssl_fail(void) { return R_SSL_UNAVAILABLE; }
HLE_NATIVE("_ZN2nn3nsd9ResolveExEPNS0_4FqdnERKS1_", nsd_fail, 'w')
HLE_NATIVE("_ZN2nn3ssl7Context6CreateENS1_10SslVersionE", ssl_fail, 'w')
HLE_NATIVE("_ZN2nn3ssl7Context15ImportServerPkiEPmPKcjNS0_17CertificateFormatE", ssl_fail, 'w')

/* ---- bcat: no delivery cache */
static uint32_t bcat_fail(void) { return R_BCAT_UNAVAILABLE; }
static uint64_t zero64(void) { return 0; }
HLE_NATIVE("_ZN2nn4bcat10InitializeEv", none, 'v')
HLE_NATIVE("_ZN2nn4bcat25MountDeliveryCacheStorageEv", bcat_fail, 'w')
HLE_NATIVE("_ZN2nn4bcat27UnmountDeliveryCacheStorageEv", none, 'v')
HLE_NATIVE("_ZN2nn4bcat24RequestSyncDeliveryCacheEPNS0_21DeliveryCacheProgressE", bcat_fail, 'w')
HLE_NATIVE("_ZN2nn4bcat30CancelSyncDeliveryCacheRequestEv", none, 'v')
HLE_NATIVE("_ZN2nn4bcat21DeliveryCacheProgressC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn4bcat21DeliveryCacheProgressD1Ev", none, 'v')
HLE_NATIVE("_ZN2nn4bcat21DeliveryCacheProgress6UpdateEv", none, 'v')
HLE_NATIVE("_ZN2nn4bcat22DeliveryCacheDirectoryC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn4bcat22DeliveryCacheDirectoryD1Ev", none, 'v')
HLE_NATIVE("_ZN2nn4bcat22DeliveryCacheDirectory4OpenERKNS0_13DirectoryNameE", bcat_fail, 'w')
HLE_NATIVE("_ZN2nn4bcat22DeliveryCacheDirectory4ReadEPiPNS0_27DeliveryCacheDirectoryEntryEi", bcat_fail, 'w')
HLE_NATIVE("_ZN2nn4bcat22DeliveryCacheDirectory5CloseEv", none, 'v')
HLE_NATIVE("_ZN2nn4bcat17DeliveryCacheFileC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn4bcat17DeliveryCacheFileD1Ev", none, 'v')
HLE_NATIVE("_ZN2nn4bcat17DeliveryCacheFile4OpenERKNS0_13DirectoryNameERKNS0_8FileNameE", bcat_fail, 'w')
HLE_NATIVE("_ZN2nn4bcat17DeliveryCacheFile4ReadEPmlPvm", bcat_fail, 'w')
HLE_NATIVE("_ZN2nn4bcat17DeliveryCacheFile5CloseEv", none, 'v')
HLE_NATIVE("_ZN2nn4bcat17DeliveryCacheFile7GetSizeEv", zero64, 'x')
HLE_NATIVE("_ZN2nn4bcat17DeliveryCacheFile9GetDigestEv", zero64, 'x')

/* ---- prepo: play reports are built and dropped (all succeed) */
HLE_NATIVE("_ZN2nn5prepo10PlayReportC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn5prepo10PlayReport9SetBufferEPvm", none, 'v')
HLE_NATIVE("_ZN2nn5prepo10PlayReport10SetEventIdEPKc", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo10PlayReport20SetOptInCheckEnabledEb", none, 'v')
HLE_NATIVE("_ZN2nn5prepo10PlayReport3AddEPKcRKNS0_10Any64BitIdE", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo10PlayReport3AddEPKcRKNS0_5ArrayE", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo10PlayReport3AddEPKcS3_", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo10PlayReport3AddEPKcb", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo10PlayReport3AddEPKcl", ok, 'w')
HLE_FUNC("_ZN2nn5prepo10PlayReport3AddEPKcd", prepo_add_double) { c->x[0] = 0; }   /* the value is in d0 */
HLE_FUNC("_ZN2nn5prepo10PlayReport3AddEPKcf", prepo_add_float) { c->x[0] = 0; }
HLE_NATIVE("_ZN2nn5prepo10PlayReport4SendERKNS_7account3UidE", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo5ArrayC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn5prepo5Array9SetBufferEPvm", none, 'v')
HLE_NATIVE("_ZN2nn5prepo5Array3AddEPKc", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo5Array3AddERKNS0_10Any64BitIdE", ok, 'w')
HLE_NATIVE("_ZN2nn5prepo5Array3AddEl", ok, 'w')
HLE_FUNC("_ZN2nn5prepo5Array3AddEd", prepo_array_double) { c->x[0] = 0; }
HLE_FUNC("_ZN2nn5prepo5Array3AddEf", prepo_array_float) { c->x[0] = 0; }
HLE_NATIVE("_ZN2nn5prepo12AsyncContextD1Ev", none, 'v')
HLE_NATIVE("_ZN2nn5prepo12AsyncContext9GetResultEv", ok, 'w')

/* ---- ngc: the profanity filter finds nothing */
static uint32_t ngc_check(uint32_t *flags, uint32_t pattern, const char **words, uint64_t count) {
    (void)pattern; (void)words;
    if (flags) memset(flags, 0, count * sizeof *flags);
    return 0;
}
HLE_NATIVE("_ZN2nn3ngc15ProfanityFilterC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn3ngc15ProfanityFilterD1Ev", none, 'v')
HLE_NATIVE("_ZN2nn3ngc15ProfanityFilter10InitializeEPvm", ok, 'w')
HLE_NATIVE("_ZN2nn3ngc15ProfanityFilter8FinalizeEv", ok, 'w')
HLE_NATIVE("_ZN2nn3ngc15ProfanityFilter19CheckProfanityWordsEPjjPPKcm", ngc_check, 'w')

/* ---- applets: shop, web pages and the software keyboard return "cancelled" */
static uint32_t cancelled(void) { return R_APPLET_CANCELLED; }
static uint64_t work_size(void) { return 0x1000; }
HLE_NATIVE("_ZN2nn2ec30ShowShopApplicationInformationENS_13ApplicationIdERKNS_7account10UserHandleE", none, 'v')
HLE_NATIVE("_ZN2nn2ec30ShowShopApplicationInformationERKNS_7account10UserHandleE", none, 'v')
HLE_NATIVE("_ZN2nn3web14ShowWebPageArgC1EPKc", none, 'v')
HLE_NATIVE("_ZN2nn3web14ShowWebPageArg14SetCallbackUrlEPKc", none, 'v')
HLE_NATIVE("_ZN2nn3web14ShowWebPageArg18SetCallbackableUrlEPKc", none, 'v')
HLE_NATIVE("_ZN2nn3web14ShowWebPageArg17SetPointerEnabledEb", none, 'v')
HLE_NATIVE("_ZN2nn3web14ShowWebPageArg6SetUidERKNS_7account3UidE", none, 'v')
HLE_NATIVE("_ZN2nn3web18WebPageReturnValueC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn3web11ShowWebPageEPNS0_18WebPageReturnValueERKNS0_14ShowWebPageArgE", cancelled, 'w')
HLE_NATIVE("_ZN2nn3web22ShowOfflineHtmlPageArgC1EPKc", none, 'v')
HLE_NATIVE("_ZN2nn3web22ShowOfflineHtmlPageArg17SetPointerEnabledEb", none, 'v')
HLE_NATIVE("_ZN2nn3web26OfflineHtmlPageReturnValueC1Ev", none, 'v')
HLE_NATIVE("_ZN2nn3web19ShowOfflineHtmlPageEPNS0_26OfflineHtmlPageReturnValueERKNS0_22ShowOfflineHtmlPageArgE", cancelled, 'w')
HLE_NATIVE("_ZN2nn5swkbd25GetRequiredWorkBufferSizeEb", work_size, 'x')
HLE_NATIVE("_ZN2nn5swkbd27GetRequiredStringBufferSizeEv", work_size, 'x')
HLE_NATIVE("_ZN2nn5swkbd10MakePresetEPNS0_14KeyboardConfigENS0_6PresetE", none, 'v')
HLE_NATIVE("_ZN2nn5swkbd16SetGuideTextUtf8EPNS0_14KeyboardConfigEPKc", none, 'v')
HLE_NATIVE("_ZN2nn5swkbd18SetInitialTextUtf8EPNS0_15ShowKeyboardArgEPKc", none, 'v')
HLE_NATIVE("_ZN2nn5swkbd12ShowKeyboardEPNS0_6StringERKNS0_15ShowKeyboardArgE", cancelled, 'w')

/* ---- ldn: local wireless is never available */
static uint32_t ipv4(uint32_t a, uint32_t b, uint32_t c, uint32_t d) { return (a & 255) << 24 | (b & 255) << 16 | (c & 255) << 8 | (d & 255); }
HLE_NATIVE("_ZN2nn3ldn8GetStateEv", ok, 'w')   /* State_None */
HLE_NATIVE("_ZN2nn3ldn15MakeIpv4AddressEhhhh", ipv4, 'w')

/* ---- oe: the calls TOTK does not make */
static void display_version(char *out) { if (out) { memset(out, 0, 16); memcpy(out, "1.0.2", 5); } }
static void pseudo_device_id(uint8_t *out) { if (out) for (int i = 0; i < 16; i++) out[i] = (uint8_t)(0x5a ^ i * 37); }
static uint32_t perf_config(uint32_t mode) { return mode == 0 ? 0x00020003u : 0x00020001u; }   /* handheld / docked */
static uint32_t execute_program(void) { runtime_fail("nn::oe::ExecuteProgram (the game asked to restart into another program)"); }
HLE_NATIVE("_ZN2nn2oe16EnableScreenShotEv", none, 'v')
HLE_NATIVE("_ZN2nn2oe17DisableScreenShotEv", none, 'v')
HLE_NATIVE("_ZN2nn2oe17GetDisplayVersionEPNS0_14DisplayVersionE", display_version, 'v')
HLE_NATIVE("_ZN2nn2oe17GetPseudoDeviceIdEPNS_4util4UuidE", pseudo_device_id, 'v')
HLE_NATIVE("_ZN2nn2oe27GetPerformanceConfigurationENS0_15PerformanceModeE", perf_config, 'w')
HLE_NATIVE("_ZN2nn2oe31EnterExitRequestHandlingSectionEv", none, 'v')
HLE_NATIVE("_ZN2nn2oe31LeaveExitRequestHandlingSectionEv", none, 'v')
HLE_NATIVE("_ZN2nn2oe14ExecuteProgramEiPKvm", execute_program, 'w')

/* ---- ro: the movie module initialises the NRO loader; Pikmin 4 ships no NRO, so nothing is ever loaded */
HLE_NATIVE("_ZN2nn2ro10InitializeEv", ok, 'w')
HLE_NATIVE("_ZN2nn2ro18RegisterModuleInfoEPNS0_16RegistrationInfoEPKv", ok, 'w')
HLE_NATIVE("_ZN2nn2ro12UnloadModuleEPNS0_6ModuleE", ok, 'w')
