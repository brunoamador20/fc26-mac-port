/* Only app launches carry this envelope. Test boots leave their process untouched. */
#import <Foundation/Foundation.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <crt_externs.h>

/* LaunchServices may discard stderr before the normal log is opened. */
static int fc26_bootstrap_failure(void) {
    NSString *dir = [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Logs/MacNativeGames"];
    [NSFileManager.defaultManager createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
    NSString *path = [dir stringByAppendingPathComponent:@"fc26-bootstrap-error.log"];
    NSString *message = [NSString stringWithFormat:@"%@ — O FC 26 não conseguiu preparar o ambiente ou abrir o log.\n", NSDate.date];
    [message writeToFile:path atomically:YES encoding:NSUTF8StringEncoding error:nil];
    fprintf(stderr, "[launcher] Falha na abertura. Veja %s\n", path.fileSystemRepresentation);
    return 1;
}
static int fc26_apply_app_bootstrap(void) {
    const char *raw = getenv("FC26_APP_BOOTSTRAP");
    if (!raw) return 0;
    @autoreleasepool {
        NSData *data = [@(raw) dataUsingEncoding:NSUTF8StringEncoding];
        if (!data) return fc26_bootstrap_failure();
        NSDictionary *p = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if (![p isKindOfClass:NSDictionary.class] || ![p[@"environment"] isKindOfClass:NSDictionary.class] ||
            ![p[@"work"] isKindOfClass:NSString.class] || ![p[@"log"] isKindOfClass:NSString.class] ||
            ![p[@"previousLog"] isKindOfClass:NSString.class]) return fc26_bootstrap_failure();
        NSDictionary *env = p[@"environment"];
        for (id k in env) if (![k isKindOfClass:NSString.class] || ![env[k] isKindOfClass:NSString.class]) return fc26_bootstrap_failure();
        if (chdir([p[@"work"] fileSystemRepresentation])) return fc26_bootstrap_failure();
        NSFileManager *fm = NSFileManager.defaultManager;
        NSError *error = nil;
        if ([fm fileExistsAtPath:p[@"previousLog"]] && ![fm removeItemAtPath:p[@"previousLog"] error:&error]) return fc26_bootstrap_failure();
        if ([fm fileExistsAtPath:p[@"log"]] && ![fm moveItemAtPath:p[@"log"] toPath:p[@"previousLog"] error:&error]) return fc26_bootstrap_failure();
        FILE *log = fopen([p[@"log"] fileSystemRepresentation], "w");
        if (!log) return fc26_bootstrap_failure();
        int out = dup2(fileno(log), STDOUT_FILENO), err = dup2(fileno(log), STDERR_FILENO);
        fclose(log);
        if (out < 0 || err < 0) return fc26_bootstrap_failure();
        /* Remove LaunchServices additions too: restore exactly the old exec environment. */
        NSMutableArray *keys = [NSMutableArray array];
        for (char **e = *_NSGetEnviron(); *e; ++e) {
            NSString *entry = @(*e); NSRange equal = [entry rangeOfString:@"="];
            if (equal.location != NSNotFound) [keys addObject:[entry substringToIndex:equal.location]];
        }
        for (NSString *key in keys) unsetenv(key.UTF8String);
        for (NSString *key in env) if (setenv(key.UTF8String, [env[key] UTF8String], 1)) return fc26_bootstrap_failure();
        fprintf(stderr, "[launcher] work %s, present %s Hz, display %s, fullscreen %s, window %s, drawable scale %s, MetalFX %s, sound on\n",
                [p[@"work"] UTF8String], getenv("DM_PRESENT_HZ") ?: "?", getenv("FC26_DISPLAY") ?: "?",
                getenv("FC26_FULLSCREEN") ? "yes" : "no", getenv("TOTK_WINDOW_SIZE") ?: "?",
                getenv("TOTK_DRAWABLE_SCALE") ?: "1", getenv("TOTK_MFX_OUTPUT") ? "on" : "off");
        return 0;
    }
}
