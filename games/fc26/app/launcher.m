/* FC 26 launcher: a settings window, then the game.
   The app is a small bundle; the game's data stay in the work folder named by Info.plist's FC26WorkFolder (or FC26_WORK),
   so nothing large is copied. Settings are saved at every change (org.macnativegames.fc26) and shown again next time.
   What each setting does in the runtime:
   - Monitor (FC26_DISPLAY), window or full screen (FC26_FULLSCREEN), window size (TOTK_WINDOW_SIZE), the full-screen
     output resolution (TOTK_DRAWABLE_SCALE relative to the monitor's pixels) and the scaler (MetalFX spatial upscaling of
     the game's picture to the output, TOTK_MFX_UPSCALE / TOTK_MFX_OUTPUT, or plain linear scaling).
   - Info: the FPS / resolution HUD (DM_HUD_RENDER).
   The game runs at a Switch 60 Hz present base (runtime/system_services.c). It has no game patch and no mod yet: the
   launcher sets none (runtime/game_patches.c, FC26_PATCHES). Not needed for story 2 (boot to nnMain): `make boot` runs
   the runtime without it. FC26_BINARY and FC26_VERSION_DIR come from the Makefile (assets/game.json). */
#import <Cocoa/Cocoa.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>

#ifndef FC26_BINARY
#define FC26_BINARY "fc26-native"
#endif
#ifndef FC26_VERSION_DIR
#define FC26_VERSION_DIR "v100"
#endif

static BOOL portuguese(void) { return [NSLocale.preferredLanguages.firstObject hasPrefix:@"pt"]; }
#define T(pt, en) (portuguese() ? @pt : @en)

static const int sizes[][2] = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440}};
static const int outputs[] = {0, 2160, 1440, 1080, 900};   /* 0 = the monitor's native pixels, else the height of a 16:9 output */

static NSString *work_folder(void) {
    const char *e = getenv("FC26_WORK");
    return e && *e ? @(e) : [NSBundle.mainBundle objectForInfoDictionaryKey:@"FC26WorkFolder"];
}
static NSString *binary_path(void) { return [work_folder() stringByAppendingPathComponent:@"build/" FC26_BINARY]; }
static NSSize screen_pixels(NSScreen *s) { CGFloat k = s.backingScaleFactor > 0 ? s.backingScaleFactor : 1; return NSMakeSize(round(s.frame.size.width * k), round(s.frame.size.height * k)); }
static NSString *screen_name(NSScreen *s) { return s.localizedName ?: @"?"; }

@interface Launcher : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property NSWindow *window;
@property NSPopUpButton *size, *monitor, *output;
@property NSSegmentedControl *display, *scaler;
@property NSButton *hud, *play; @property NSTextField *note;
@property BOOL launch;
@end

@implementation Launcher
- (NSTextField *)label:(NSString *)s { NSTextField *l = [NSTextField labelWithString:s]; l.alignment = NSTextAlignmentRight; return l; }
- (NSPopUpButton *)popup:(NSArray<NSString *> *)items { NSPopUpButton *p = [NSPopUpButton new]; [p addItemsWithTitles:items]; p.target = self; p.action = @selector(changed:); return p; }
- (NSSegmentedControl *)segments:(NSArray<NSString *> *)labels {
    return [NSSegmentedControl segmentedControlWithLabels:labels trackingMode:NSSegmentSwitchTrackingSelectOne target:self action:@selector(changed:)];
}
- (void)applicationDidFinishLaunching:(NSNotification *)n {
    (void)n;
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    self.monitor = [NSPopUpButton new]; self.monitor.target = self; self.monitor.action = @selector(monitorChanged:);
    for (NSScreen *s in NSScreen.screens) {
        NSSize px = screen_pixels(s);
        [self.monitor addItemWithTitle:[NSString stringWithFormat:@"%@ — %.0f × %.0f, %ld Hz", screen_name(s), px.width, px.height, (long)s.maximumFramesPerSecond]];
    }
    self.display = [self segments:@[T("Janela", "Window"), T("Tela cheia", "Full screen")]];
    NSMutableArray *sizeTitles = [NSMutableArray array];
    for (unsigned i = 0; i < sizeof sizes / sizeof *sizes; i++) [sizeTitles addObject:[NSString stringWithFormat:@"%d × %d", sizes[i][0], sizes[i][1]]];
    self.size = [self popup:sizeTitles];
    self.output = [NSPopUpButton new]; self.output.target = self; self.output.action = @selector(changed:);
    self.scaler = [self segments:@[T("MetalFX (mais nítido)", "MetalFX (sharper)"), T("Normal", "Plain")]];
    self.hud = [NSButton checkboxWithTitle:T("Mostrar FPS e resolução (a tecla 1 esconde)", "Show FPS and resolution (key 1 hides it)") target:self action:@selector(changed:)];
    self.note = [NSTextField wrappingLabelWithString:@""]; self.note.textColor = NSColor.secondaryLabelColor; self.note.font = [NSFont systemFontOfSize:11];
    self.play = [NSButton buttonWithTitle:T("Jogar", "Play") target:self action:@selector(start:)]; self.play.keyEquivalent = @"\r";
    NSButton *quit = [NSButton buttonWithTitle:T("Sair", "Quit") target:NSApp action:@selector(terminate:)]; quit.keyEquivalent = @"\033";

    NSGridView *grid = [NSGridView gridViewWithViews:@[
        @[[self label:T("Monitor", "Monitor")], self.monitor],
        @[[self label:T("Tela", "Display")], self.display],
        @[[self label:T("Tamanho da janela", "Window size")], self.size],
        @[[self label:T("Resolução de saída", "Output resolution")], self.output],
        @[[self label:T("Escala", "Scaling")], self.scaler],
        @[[self label:T("Informação", "Info")], self.hud],
    ]];
    grid.rowSpacing = 10; grid.columnSpacing = 12; [grid columnAtIndex:0].xPlacement = NSGridCellPlacementTrailing;
    NSStackView *buttons = [NSStackView stackViewWithViews:@[quit, self.play]];
    NSStackView *stack = [NSStackView stackViewWithViews:@[grid, self.note, buttons]];
    stack.orientation = NSUserInterfaceLayoutOrientationVertical; stack.alignment = NSLayoutAttributeTrailing; stack.spacing = 16;
    stack.edgeInsets = NSEdgeInsetsMake(20, 20, 20, 20);
    self.window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 600, 320) styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
                                                backing:NSBackingStoreBuffered defer:NO];
    self.window.title = @"FC 26"; self.window.contentView = stack; self.window.delegate = self;
    [self.note.widthAnchor constraintEqualToConstant:520].active = YES;

    [self load:d];
    [self refresh];
    [self.window center]; [self.window makeKeyAndOrderFront:nil]; [NSApp activateIgnoringOtherApps:YES];
}
- (NSScreen *)chosenScreen { NSInteger i = self.monitor.indexOfSelectedItem; NSArray *all = NSScreen.screens; return i >= 0 && i < (NSInteger)all.count ? all[i] : NSScreen.mainScreen; }
/* The output resolutions this monitor can show: native first, then the 16:9 ones that fit. */
- (void)fillOutputs:(int)want {
    [self.output removeAllItems];
    NSSize px = screen_pixels(self.chosenScreen); int pick = 0, k = 0;
    for (unsigned i = 0; i < sizeof outputs / sizeof *outputs; i++) {
        int h = outputs[i];
        if (h && h > px.height) continue;
        [self.output addItemWithTitle:h ? [NSString stringWithFormat:@"%d × %d", h * 16 / 9, h] : [NSString stringWithFormat:T("Nativa do monitor (%.0f × %.0f)", "The monitor's native (%.0f × %.0f)"), px.width, px.height]];
        self.output.lastItem.tag = h; if (h == want) pick = k; k++;
    }
    [self.output selectItemAtIndex:pick];
}
- (void)load:(NSUserDefaults *)d {
    NSString *m = [d stringForKey:@"monitor"]; NSArray *all = NSScreen.screens; NSUInteger mi = [all indexOfObject:NSScreen.mainScreen];
    if (mi == NSNotFound) mi = 0;
    for (NSUInteger i = 0; i < all.count; i++) if (m && [screen_name(all[i]) isEqualToString:m]) mi = i;
    [self.monitor selectItemAtIndex:(NSInteger)mi];
    self.display.selectedSegment = [d boolForKey:@"fullscreen"];
    NSInteger s = [d objectForKey:@"size"] ? [d integerForKey:@"size"] : 2; [self.size selectItemAtIndex:s >= 0 && s < 4 ? s : 2];
    self.scaler.selectedSegment = [d objectForKey:@"metalfx"] && ![d boolForKey:@"metalfx"] ? 1 : 0;
    [self fillOutputs:(int)[d integerForKey:@"output"]];
    self.hud.state = [d objectForKey:@"hud"] ? [d boolForKey:@"hud"] : YES;
}
/* Every change is saved at once (and written to disk), so the next start shows the same choices. */
- (void)monitorChanged:(id)sender { (void)sender; [self fillOutputs:(int)self.output.selectedItem.tag]; [self refresh]; [self save]; }
- (void)changed:(id)sender { (void)sender; [self refresh]; [self save]; }
- (void)refresh {
    BOOL full = self.display.selectedSegment == 1;
    self.size.enabled = !full; self.output.enabled = full;
    NSMutableString *s = [NSMutableString string];
    self.play.enabled = YES;
    if (!work_folder() || ![NSFileManager.defaultManager isExecutableFileAtPath:binary_path()]) {
        [s appendFormat:T("O jogo não está em %@.", "The game is not in %@."), work_folder() ?: @"?"]; self.play.enabled = NO;
    }
    self.note.stringValue = s; self.note.hidden = !s.length;
}
- (void)save {
    NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
    [d setBool:self.display.selectedSegment == 1 forKey:@"fullscreen"]; [d setInteger:self.size.indexOfSelectedItem forKey:@"size"];
    [d setInteger:self.output.selectedItem.tag forKey:@"output"]; [d setBool:self.scaler.selectedSegment == 0 forKey:@"metalfx"];
    [d setObject:screen_name(self.chosenScreen) forKey:@"monitor"]; [d setBool:self.hud.state forKey:@"hud"];
    CFPreferencesAppSynchronize(kCFPreferencesCurrentApplication);   // the launcher then replaces itself with the game (exec)
}
- (void)start:(id)sender { (void)sender; [self save]; self.launch = YES; [NSApp stop:nil]; [self.window orderOut:nil];
    NSEvent *e = [NSEvent otherEventWithType:NSEventTypeApplicationDefined location:NSZeroPoint modifierFlags:0 timestamp:0 windowNumber:0 context:nil subtype:0 data1:0 data2:0];
    [NSApp postEvent:e atStart:YES]; }
- (void)windowWillClose:(NSNotification *)n { (void)n; if (!self.launch) { [self save]; [NSApp terminate:nil]; } }
@end

static void fail(NSString *s) {
    NSAlert *a = [NSAlert new]; a.messageText = T("O FC 26 não conseguiu iniciar", "FC 26 could not start"); a.informativeText = s; [a runModal];
}
static BOOL make_dir(NSString *p) { return [NSFileManager.defaultManager createDirectoryAtPath:p withIntermediateDirectories:YES attributes:nil error:nil]; }

int main(int argc, char **argv) {
    (void)argc; (void)argv;
    @autoreleasepool {
        [NSApplication sharedApplication]; NSApp.activationPolicy = NSApplicationActivationPolicyRegular;
        Launcher *l = [Launcher new]; NSApp.delegate = l;
        [NSApp run];
        if (!l.launch) return 0;
        NSUserDefaults *d = NSUserDefaults.standardUserDefaults;
        NSString *work = work_folder(), *home = NSHomeDirectory();
        NSString *data = [home stringByAppendingPathComponent:@"Library/Application Support/MacNativeGames/FC26"];
        NSString *logs = [home stringByAppendingPathComponent:@"Library/Logs/MacNativeGames"];
        /* The game slot is the work folder's (<work>/analysis/game-slot), the one `make boot` uses by default: one queue, so
           an agent's test and the player's game never run together and the player's goes first (runtime/game_slot.c). */
        NSString *profile = [data stringByAppendingPathComponent:@"profile"], *slot = [work stringByAppendingPathComponent:@"analysis/game-slot"];
        if (!make_dir(profile) || !make_dir(slot) || !make_dir(logs)) { fail([NSString stringWithFormat:@"%@", data]); return 1; }
        if (chdir(work.fileSystemRepresentation)) { fail(work); return 1; }   // the runtime reads extracted/ and rewritten/ relative to it

        unsetenv("FC26_PATCHES");   // FC 26 has no game patch yet
        setenv("DM_PRESENT_HZ", "60", 1);
        NSArray<NSScreen *> *all = NSScreen.screens; NSUInteger mi = [all indexOfObject:NSScreen.mainScreen];
        if (mi == NSNotFound) mi = 0;
        for (NSUInteger i = 0; i < all.count; i++) if ([screen_name(all[i]) isEqualToString:[d stringForKey:@"monitor"]]) mi = i;
        setenv("FC26_DISPLAY", [NSString stringWithFormat:@"%lu", (unsigned long)mi].UTF8String, 1);
        BOOL full = [d boolForKey:@"fullscreen"];
        if (full) {
            setenv("FC26_FULLSCREEN", "1", 1);
            int h = (int)[d integerForKey:@"output"]; NSSize px = screen_pixels(all.count ? all[mi] : NSScreen.mainScreen);
            if (h > 0 && h < px.height) setenv("TOTK_DRAWABLE_SCALE", [NSString stringWithFormat:@"%.4f", h / px.height].UTF8String, 1);
        }
        NSInteger s = [d integerForKey:@"size"]; if (s < 0 || s > 3) s = 2;
        setenv("TOTK_WINDOW_SIZE", [NSString stringWithFormat:@"%dx%d", sizes[s][0], sizes[s][1]].UTF8String, 1);
        if (![d objectForKey:@"metalfx"] || [d boolForKey:@"metalfx"]) { setenv("TOTK_MFX_UPSCALE", "1", 1); setenv("TOTK_MFX_OUTPUT", "1", 1); }
        if ([d objectForKey:@"hud"] && ![d boolForKey:@"hud"]) setenv("TOTK_FPS_OVERLAY", "0", 1); else setenv("DM_HUD_RENDER", "1", 1);
        setenv("TOTK_ROMFS_MODS", "0", 1);   // no mod

        setenv("TOTK_PROFILE_DIR", profile.fileSystemRepresentation, 1);
        setenv("TOTK_GAME_SLOT_DIR", slot.fileSystemRepresentation, 1);
        setenv("TOTK_ROMFS_PROOF_DIR", data.fileSystemRepresentation, 1);
        NSString *preferred = NSLocale.preferredLanguages.firstObject; if (preferred) setenv("TOTK_LOCALE", preferred.UTF8String, 1);
        /* The graphics settings the kit's earlier launchers use. TODO(mac): confirm each for FC 26 at the first frame (story 4). */
        setenv("TOTK_GPU_ALLOW_SUBMIT", "1", 1); setenv("TOTK_GPU_WIDEN", "1", 1); setenv("TOTK_GPU_BLOCKRT", "1", 1);
        setenv("TOTK_GPU_MIDCLEAR", "1", 1); setenv("TOTK_GPU_BUDGET_MB", "5000", 1);
        setenv("DM_PRESENT_LINK_FALLBACK", "1", 1);   // keep presenting when macOS pauses the display link for a window it thinks covered
        setenv("TOTK_SLOT_OWNER", "user", 1); setenv("TOTK_SLOT_PURPOSE", "player", 1);
        unsetenv("TOTK_HEADLESS");
        { NSString *cmds = [data stringByAppendingPathComponent:@"input.txt"]; FILE *cf = fopen(cmds.fileSystemRepresentation, "w"); if (cf) fclose(cf);
          setenv("TOTK_INPUT_FILE", cmds.fileSystemRepresentation, 1); }   // echo "shot ~/Desktop/shot.png" >> it

        NSString *log = [logs stringByAppendingPathComponent:@"fc26.log"], *prev = [logs stringByAppendingPathComponent:@"fc26.previous.log"];
        [NSFileManager.defaultManager removeItemAtPath:prev error:nil]; [NSFileManager.defaultManager moveItemAtPath:log toPath:prev error:nil];
        FILE *lf = fopen(log.fileSystemRepresentation, "w"); if (lf) { dup2(fileno(lf), STDOUT_FILENO); dup2(fileno(lf), STDERR_FILENO); fclose(lf); }
        fprintf(stderr, "[launcher] work %s, present %s Hz, display %s, fullscreen %s, window %s, drawable scale %s, MetalFX %s\n",
                work.UTF8String, getenv("DM_PRESENT_HZ"), getenv("FC26_DISPLAY"), full ? "yes" : "no", getenv("TOTK_WINDOW_SIZE"),
                getenv("TOTK_DRAWABLE_SCALE") ?: "1", getenv("TOTK_MFX_OUTPUT") ? "on" : "off");
        NSString *binary = binary_path();
        char *const args[] = {(char *)binary.fileSystemRepresentation, "rewritten/" FC26_VERSION_DIR, "boot", NULL};
        execv(args[0], args);
        fprintf(stderr, "[launcher] execv failed: %s\n", strerror(errno));
        fail([NSString stringWithFormat:T("Não foi possível iniciar o jogo. Veja %@.", "Starting the game failed. See %@."), log]);
        return 1;
    }
}
