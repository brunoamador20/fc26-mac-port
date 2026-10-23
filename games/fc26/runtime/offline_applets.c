/* Library applets FC 26 opens that need a connection, answered by name (runtime_offline_applet_override, called from
   services.c runtime_override) as if the player closed them at once (story 4; docs/SERVICOS_NUVEM.md):
     nn::web::ShowWebPage          the web browser applet: Result 0, exit reason 0, no last URL
     nn::web::RequestExitWebPage   no page is open: nothing to close
     nn::ec::ShowShop*             the Nintendo eShop applet (product list, details, add-on content list, consumable item,
                                   enter-code scene): Result 0, nothing bought
   On the Switch these start a library applet that takes the screen until the player leaves it; offline neither the
   eShop nor a web page can load, and the host has no applet system (the kit answers swkbd and err by name the same way).
   A name is matched by its qualified name only, the mangled prefix "_ZN2nn<n><namespace><n><function>E" before the
   parameter list, so every overload is taken; the parameters are not read (only ShowWebPage's return value is written).
   The ShowWebPageArg setters (SetCallbackUrl, SetDisplayUrlKind, ...) and nn::ec::MakeNsUid only fill the game's own
   structures and run natively in the sdk. */
#include "runtime.h"
#include <stdio.h>
#include <string.h>

enum { WEB_PAGE_RETURN_VALUE_SIZE = 0x2000 };
/* nn::web::ShowWebPage(WebPageReturnValue *out, const ShowWebPageArg &arg).
   In SDK 19.3.4 nn::web::WebPageReturnValue::DataSize (sdk+0x9c9528) is 8192 (0x2000) bytes and the constructor
   (sdk+0x554d44) zeroes 0x2000 bytes. The format is a TLV list: u16 count at +0; the first entry begins at +8;
   each entry is u16 kind, u16 size, 4 bytes padding, then data (next entry at entry + 8 + size).
   GetWebExitReason (sdk+0x554d50) searches for kind 1 (u32 at entry+8; default 0x14 if absent), GetLastUrl
   (sdk+0x554da0) searches for kind 2, and GetLastUrlSize (sdk+0x554df0) searches for kind 3 (u64 at entry+8; default 0).
   Zeroing everything made GetWebExitReason return 0x14. We write one entry: count=1, entry at +8 with kind=1,
   size=4, and u32 exit reason = 0 at +16 (as libnx/kit uses for the close button). */
static uint32_t show_web_page(uint8_t *out, const void *arg) {
    (void)arg;
    if (out) {
        dm_guest_write_prepare(out, WEB_PAGE_RETURN_VALUE_SIZE);
        memset(out, 0, WEB_PAGE_RETURN_VALUE_SIZE);
        uint16_t count = 1;
        uint16_t kind = 1;
        uint16_t size = 4;
        uint32_t exit_reason = 0;
        memcpy(out + 0, &count, sizeof count);
        memcpy(out + 8, &kind, sizeof kind);
        memcpy(out + 10, &size, sizeof size);
        memcpy(out + 16, &exit_reason, sizeof exit_reason);
    }
    fprintf(stderr, "[totk-net] nn::web::ShowWebPage: closed at once (offline), exit reason 0\n");
    return 0;
}
/* Another ShowWebPage overload: its return value's place is not known, so nothing is written. */
static uint32_t show_web_page_other(void) {
    fprintf(stderr, "[totk-net] nn::web::ShowWebPage (other overload): closed at once (offline), return value not written\n");
    return 0;
}
static uint32_t request_exit_web_page(void) { return 0; }
static uint32_t show_shop(void) {
    fprintf(stderr, "[totk-net] nn::ec shop applet: closed at once (offline), nothing bought\n");
    return 0;
}

static const struct { const char *space, *function, *params; void *fn; } applets[] = {
    {"web", "ShowWebPage", "PNS0_18WebPageReturnValueE", show_web_page},   /* params: first parameter WebPageReturnValue* */
    {"web", "ShowWebPage", "", show_web_page_other},
    {"web", "RequestExitWebPage", "", request_exit_web_page},
    {"ec", "ShowShopProductList", "", show_shop},
    {"ec", "ShowShopProductDetails", "", show_shop},
    {"ec", "ShowShopAddOnContentList", "", show_shop},
    {"ec", "ShowShopConsumableItemDetail", "", show_shop},
    {"ec", "ShowShopEnterCodeScene", "", show_shop},
};

/* "_ZN2nn" <len><space> <len><function> "E" <params>: the mangled prefix of nn::<space>::<function>(<params>...). */
int runtime_offline_applet_prefix(char *out, size_t cap, unsigned index) {
    if (index >= sizeof applets / sizeof *applets) return -1;
    int n = snprintf(out, cap, "_ZN2nn%zu%s%zu%sE%s", strlen(applets[index].space), applets[index].space,
                     strlen(applets[index].function), applets[index].function, applets[index].params);
    return n > 0 && (size_t)n < cap ? n : -1;
}
void *runtime_offline_applet_override(const char *name) {
    if (strncmp(name, "_ZN2nn", 6)) return NULL;
    char prefix[128];
    for (unsigned i = 0; i < sizeof applets / sizeof *applets; i++) {
        int n = runtime_offline_applet_prefix(prefix, sizeof prefix, i);
        if (n > 0 && !strncmp(name, prefix, (size_t)n)) return applets[i].fn;
    }
    return NULL;
}
