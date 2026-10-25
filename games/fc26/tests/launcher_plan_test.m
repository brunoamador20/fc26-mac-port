/* The app launcher's plan (app/launcher.m, compiled here as it is, its main renamed): what the game would start with for
   the settings given, as JSON on stdout. Nothing is started and no window opens.
   usage: launcher_plan_test <work> <home> [key=bool|int ...]   (fullscreen, metalfx, hud: 0/1; size, output: n)
   The settings are registered defaults (memory only): nothing is written to ~/Library/Preferences. */
#define main launcher_main
#include "../app/launcher.m"
#undef main

int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc < 3) { fprintf(stderr, "usage: %s <work> <home> [key=value ...]\n", argv[0]); return 2; }
        NSUserDefaults *d = [[NSUserDefaults alloc] initWithSuiteName:@"org.macnativegames.fc26.plan-test"];
        NSMutableDictionary *settings = [NSMutableDictionary dictionary];
        for (int i = 3; i < argc; i++) {
            NSArray<NSString *> *kv = [@(argv[i]) componentsSeparatedByString:@"="];
            if (kv.count != 2) return 2;
            settings[kv[0]] = [@[@"fullscreen", @"metalfx", @"hud", @"FPS60"] containsObject:kv[0]] ? @(kv[1].intValue != 0) : @(kv[1].integerValue);
        }
        [d registerDefaults:settings];
        LaunchPlan *p = launch_plan(d, @(argv[1]), @(argv[2]), NSScreen.screens, NSScreen.mainScreen);
        NSDictionary *out = @{@"set": p.set, @"unset": p.unset, @"cwd": p.work, @"args": p.args, @"log": p.log,
                              @"previous_log": p.previousLog, @"profile": p.profile, @"slot": p.slot, @"input": p.input};
        NSData *json = [NSJSONSerialization dataWithJSONObject:out options:NSJSONWritingSortedKeys error:nil];
        fwrite(json.bytes, 1, json.length, stdout);
        return 0;
    }
}
