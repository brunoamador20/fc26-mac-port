/* FC 26 launcher: a settings window, then the game.
   The app is a small bundle; the game's data stay in the work folder named by Info.plist's FC26WorkFolder (or FC26_WORK),
   so nothing large is copied. Settings are saved at every change (org.macnativegames.fc26) and shown again next time.
   What each setting does in the runtime:
   - Monitor (FC26_DISPLAY), window or full screen (FC26_FULLSCREEN), window size (TOTK_WINDOW_SIZE), the full-screen
     output resolution (TOTK_DRAWABLE_SCALE relative to the monitor's pixels) and the scaler (MetalFX spatial upscaling of
     the game's picture to the output, TOTK_MFX_UPSCALE / TOTK_MFX_OUTPUT, or plain linear scaling).
   - Info: the FPS / resolution HUD (DM_HUD_RENDER).
   The rest is what tools/boot_gpu.sh gives the test boots (the GPU settings), but with the sound on, the profile and saves
   in ~/Library/Application Support/MacNativeGames/FC26/profile and the log in ~/Library/Logs/MacNativeGames/fc26.log
   (launch_plan). `"FC 26.app/Contents/MacOS/FC 26" --dry-run` prints all of it and starts nothing.
   The game runs at a Switch 60 Hz present base (runtime/system_services.c). It has no game patch and no mod yet: the
   launcher sets none (runtime/game_patches.c, FC26_PATCHES). Not needed for story 2 (boot to nnMain): `make boot` runs
   the runtime without it. FC26_BINARY and FC26_VERSION_DIR come from the Makefile (assets/game.json); so do
   FC26_RUNTIME_DIR, the work folder's subfolder with the runtime built for that version (the update's is build-update,
   `make prepare runtime OUT=<work>/build-update`), and FC26_SHADER_CACHE, that runtime's shader cache relative to the work
   folder (TOTK_SHADER_CACHE; empty: the runtime's own default, <work>/build/shader-cache, the base game's). */
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
#ifndef FC26_RUNTIME_DIR
#define FC26_RUNTIME_DIR "build"
#endif
#ifndef FC26_SHADER_CACHE
#define FC26_SHADER_CACHE ""
#endif

static BOOL portuguese(void) { return [NSLocale.preferredLanguages.firstObject hasPrefix:@"pt"]; }
#define T(pt, en) (portuguese() ? @pt : @en)

static const int sizes[][2] = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440}};
static const int outputs[] = {0, 2160, 1440, 1080, 900};   /* 0 = the monitor's native pixels, else the height of a 16:9 output */

static NSString *work_folder(void) {
    const char *e = getenv("FC26_WORK");
    return e && *e ? @(e) : [NSBundle.mainBundle objectForInfoDictionaryKey:@"FC26WorkFolder"];
}
static NSString *binary_path_in(NSString *work) { return [work stringByAppendingPathComponent:@FC26_RUNTIME_DIR "/" FC26_BINARY]; }
static NSString *binary_path(void) { return binary_path_in(work_folder()); }
static NSSize screen_pixels(NSScreen *s) { CGFloat k = s.backingScaleFactor > 0 ? s.backingScaleFactor : 1; return NSMakeSize(round(s.frame.size.width * k), round(s.frame.size.height * k)); }
static NSString *screen_name(NSScreen *s) { return s.localizedName ?: @"?"; }

@interface Launcher : NSObject <NSApplicationDelegate, NSWindowDelegate>
@property NSWindow *window;
@property NSPopUpButton *size, *monitor, *output;
@property NSSegmentedControl *display, *scaler;
@property NSButton *hud, *fps60, *play; @property NSTextField *note;
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
    self.fps60 = [NSButton checkboxWithTitle:T("60 fps (aumenta o calor e o consumo)", "60 fps (increases heat and power use)") target:self action:@selector(changed:)];
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
        @[[self label:T("Fluidez", "Smoothness")], self.fps60],
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
    self.scaler.selectedSegment = [d boolForKey:@"metalfx"] ? 0 : 1;   // plain unless MetalFX was chosen (launch_plan)
    [self fillOutputs:(int)[d integerForKey:@"output"]];
    self.fps60.state = [d boolForKey:@"FPS60"];
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
    [d setBool:self.fps60.state forKey:@"FPS60"];
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

/* What the game starts with, from the saved settings: the variables set and cleared, the folder, the command and the log.
   The start and the dry run (--dry-run or FC26_LAUNCHER_DRYRUN=1: print it, start nothing) share it. */
@interface LaunchPlan : NSObject
@property NSString *work, *data, *profile, *slot, *logs, *log, *previousLog, *input;
@property NSArray<NSString *> *args, *unset;
@property NSMutableDictionary<NSString *, NSString *> *set;
@end
@implementation LaunchPlan
@end

static LaunchPlan *launch_plan(NSUserDefaults *d, NSString *work, NSString *home, NSArray<NSScreen *> *all, NSScreen *main_screen) {
    LaunchPlan *p = [LaunchPlan new]; NSMutableDictionary<NSString *, NSString *> *e = [NSMutableDictionary dictionary];
    p.work = work; p.set = e;
    p.data = [home stringByAppendingPathComponent:@"Library/Application Support/MacNativeGames/FC26"];
    p.logs = [home stringByAppendingPathComponent:@"Library/Logs/MacNativeGames"];
    p.log = [p.logs stringByAppendingPathComponent:@"fc26.log"]; p.previousLog = [p.logs stringByAppendingPathComponent:@"fc26.previous.log"];
    /* The game slot is the work folder's (<work>/analysis/game-slot), the one `make boot` uses by default: one queue, so
       an agent's test and the player's game never run together and the player's goes first (runtime/game_slot.c). */
    p.profile = [p.data stringByAppendingPathComponent:@"profile"]; p.slot = [work stringByAppendingPathComponent:@"analysis/game-slot"];
    p.input = [p.data stringByAppendingPathComponent:@"input.txt"];   // echo "shot ~/Desktop/shot.png" >> it
    p.args = @[binary_path_in(work), @"rewritten/" FC26_VERSION_DIR, @"boot"];
    /* Only the automatic boots are silent and headless (Makefile BOOT_ENV, tools/boot_gpu.sh): the player's game has its
       sound (audio renderer and AudioOut) and its window even when started from a terminal that has those set. FC 26 has
       no game patch yet. The RomFS verification record stays the one next to the image (the boots' own), so the app's
       first start does not hash the image again (37.8 GB for the update's merged RomFS). */
    NSMutableArray<NSString *> *unset = [@[@"FC26_AUDIO", @"FC26_PATCHES", @"TOTK_AUDIO_OFF", @"TOTK_HEADLESS", @"TOTK_ROMFS_PROOF_DIR"] mutableCopy];
    /* The update's runtime keeps its translations and its shader journal apart from the base game's
       (<work>/build/shader-cache, the runtime's default), as its test boots do (tools/relatorio_update.md). */
    if (*FC26_SHADER_CACHE) e[@"TOTK_SHADER_CACHE"] = [work stringByAppendingPathComponent:@FC26_SHADER_CACHE];
    else [unset addObject:@"TOTK_SHADER_CACHE"];
    p.unset = unset;

    if ([d boolForKey:@"FPS60"]) e[@"FC26_FPS60"] = @"1";
    e[@"DM_PRESENT_HZ"] = @"60";
    NSUInteger mi = [all indexOfObject:main_screen]; if (mi == NSNotFound) mi = 0;
    for (NSUInteger i = 0; i < all.count; i++) if ([screen_name(all[i]) isEqualToString:[d stringForKey:@"monitor"]]) mi = i;
    e[@"FC26_DISPLAY"] = [NSString stringWithFormat:@"%lu", (unsigned long)mi];
    if ([d boolForKey:@"fullscreen"]) {
        e[@"FC26_FULLSCREEN"] = @"1";
        int h = (int)[d integerForKey:@"output"]; NSSize px = mi < all.count ? screen_pixels(all[mi]) : NSZeroSize;
        if (h > 0 && h < px.height) e[@"TOTK_DRAWABLE_SCALE"] = [NSString stringWithFormat:@"%.4f", h / px.height];
    }
    NSInteger s = [d objectForKey:@"size"] ? [d integerForKey:@"size"] : 2; if (s < 0 || s > 3) s = 2;
    e[@"TOTK_WINDOW_SIZE"] = [NSString stringWithFormat:@"%dx%d", sizes[s][0], sizes[s][1]];
    /* MetalFX only when chosen: the boots that reached the game's screens ran without it (TODO(mac): try it on FC 26). */
    if ([d boolForKey:@"metalfx"]) { e[@"TOTK_MFX_UPSCALE"] = @"1"; e[@"TOTK_MFX_OUTPUT"] = @"1"; }
    if ([d objectForKey:@"hud"] && ![d boolForKey:@"hud"]) e[@"TOTK_FPS_OVERLAY"] = @"0"; else e[@"DM_HUD_RENDER"] = @"1";
    e[@"TOTK_ROMFS_MODS"] = @"0";   // no mod

    e[@"TOTK_PROFILE_DIR"] = p.profile; e[@"TOTK_GAME_SLOT_DIR"] = p.slot;
    NSString *preferred = NSLocale.preferredLanguages.firstObject; if (preferred) e[@"TOTK_LOCALE"] = preferred;
    /* The graphics settings of tools/boot_gpu.sh, the boots that reach the game's first screens at 30 frames/s. */
    e[@"TOTK_GPU_ALLOW_SUBMIT"] = @"1"; e[@"TOTK_GPU_WIDEN"] = @"1"; e[@"TOTK_GPU_BLOCKRT"] = @"1";
    e[@"TOTK_GPU_MIDCLEAR"] = @"1"; e[@"TOTK_GPU_BUDGET_MB"] = @"5000";
    e[@"DM_PRESENT_LINK_FALLBACK"] = @"1";   // keep presenting when macOS pauses the display link for a window it thinks covered
    e[@"TOTK_SLOT_OWNER"] = @"user"; e[@"TOTK_SLOT_PURPOSE"] = @"player";
    e[@"TOTK_INPUT_FILE"] = p.input;
    return p;
}

static NSString *quoted(NSString *s) { return [NSString stringWithFormat:@"'%@'", [s stringByReplacingOccurrencesOfString:@"'" withString:@"'\\''"]]; }
/* The dry run: the plan as shell lines on stdout; 3 when the game is not in the work folder. */
static int dry_run(LaunchPlan *p) {
    printf("# FC 26 launcher, dry run: nothing is started\ncd %s\nunset %s\n", quoted(p.work).UTF8String,
           [[p.unset sortedArrayUsingSelector:@selector(compare:)] componentsJoinedByString:@" "].UTF8String);
    for (NSString *k in [p.set.allKeys sortedArrayUsingSelector:@selector(compare:)]) printf("export %s=%s\n", k.UTF8String, quoted(p.set[k]).UTF8String);
    printf("exec %s %s %s 2> %s\n", quoted(p.args[0]).UTF8String, p.args[1].UTF8String, p.args[2].UTF8String, quoted(p.log).UTF8String);
    if (![NSFileManager.defaultManager isExecutableFileAtPath:p.args[0]]) { fprintf(stderr, "the game is not built: %s\n", p.args[0].UTF8String); return 3; }
    return 0;
}

int main(int argc, char **argv) {
    @autoreleasepool {
        const char *dry = getenv("FC26_LAUNCHER_DRYRUN");
        if ((argc > 1 && !strcmp(argv[1], "--dry-run")) || (dry && !strcmp(dry, "1"))) {
            NSString *work = work_folder(); if (!work) { fprintf(stderr, "no work folder (Info.plist FC26WorkFolder or FC26_WORK)\n"); return 2; }
            return dry_run(launch_plan(NSUserDefaults.standardUserDefaults, work, NSHomeDirectory(), NSScreen.screens, NSScreen.mainScreen));
        }
        [NSApplication sharedApplication]; NSApp.activationPolicy = NSApplicationActivationPolicyRegular;
        Launcher *l = [Launcher new]; NSApp.delegate = l;
        [NSApp run];
        if (!l.launch) return 0;
        LaunchPlan *p = launch_plan(NSUserDefaults.standardUserDefaults, work_folder(), NSHomeDirectory(), NSScreen.screens, NSScreen.mainScreen);
        if (!make_dir(p.profile) || !make_dir(p.slot) || !make_dir(p.logs)) { fail([NSString stringWithFormat:@"%@", p.data]); return 1; }
        if (chdir(p.work.fileSystemRepresentation)) { fail(p.work); return 1; }   // the runtime reads extracted/ and rewritten/ relative to it
        for (NSString *k in p.unset) unsetenv(k.UTF8String);
        for (NSString *k in p.set) setenv(k.UTF8String, p.set[k].UTF8String, 1);
        { FILE *cf = fopen(p.input.fileSystemRepresentation, "w"); if (cf) fclose(cf); }

        [NSFileManager.defaultManager removeItemAtPath:p.previousLog error:nil]; [NSFileManager.defaultManager moveItemAtPath:p.log toPath:p.previousLog error:nil];
        FILE *lf = fopen(p.log.fileSystemRepresentation, "w"); if (lf) { dup2(fileno(lf), STDOUT_FILENO); dup2(fileno(lf), STDERR_FILENO); fclose(lf); }
        fprintf(stderr, "[launcher] work %s, present %s Hz, display %s, fullscreen %s, window %s, drawable scale %s, MetalFX %s, sound on\n",
                p.work.UTF8String, getenv("DM_PRESENT_HZ"), getenv("FC26_DISPLAY"), getenv("FC26_FULLSCREEN") ? "yes" : "no", getenv("TOTK_WINDOW_SIZE"),
                getenv("TOTK_DRAWABLE_SCALE") ?: "1", getenv("TOTK_MFX_OUTPUT") ? "on" : "off");
        char *const args[] = {(char *)p.args[0].fileSystemRepresentation, (char *)p.args[1].UTF8String, (char *)p.args[2].UTF8String, NULL};
        execv(args[0], args);
        fprintf(stderr, "[launcher] execv failed: %s\n", strerror(errno));
        fail([NSString stringWithFormat:T("Não foi possível iniciar o jogo. Veja %@.", "Starting the game failed. See %@."), p.log]);
        return 1;
    }
}
