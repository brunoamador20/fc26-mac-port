/* Only app launches carry this envelope. Test boots leave their process untouched. */
#import <Foundation/Foundation.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <crt_externs.h>

static int fc26_apply_app_bootstrap(void) {
    const char *raw = getenv("FC26_APP_BOOTSTRAP");
    if (!raw) return 0;
    @autoreleasepool {
        NSData *data = [@(raw) dataUsingEncoding:NSUTF8StringEncoding];
        if (!data) return 1;
        NSDictionary *p = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
        if (![p isKindOfClass:NSDictionary.class] || ![p[@"environment"] isKindOfClass:NSDictionary.class] ||
            ![p[@"work"] isKindOfClass:NSString.class] || ![p[@"log"] isKindOfClass:NSString.class] ||
            ![p[@"previousLog"] isKindOfClass:NSString.class]) return 1;
        NSDictionary *env = p[@"environment"];
        for (id k in env) if (![k isKindOfClass:NSString.class] || ![env[k] isKindOfClass:NSString.class]) return 1;
        if (chdir([p[@"work"] fileSystemRepresentation])) return 1;
        NSFileManager *fm = NSFileManager.defaultManager;
        NSError *error = nil;
        if ([fm fileExistsAtPath:p[@"previousLog"]] && ![fm removeItemAtPath:p[@"previousLog"] error:&error]) return 1;
        if ([fm fileExistsAtPath:p[@"log"]] && ![fm moveItemAtPath:p[@"log"] toPath:p[@"previousLog"] error:&error]) return 1;
        FILE *log = fopen([p[@"log"] fileSystemRepresentation], "w");
        if (!log) return 1;
        int out = dup2(fileno(log), STDOUT_FILENO), err = dup2(fileno(log), STDERR_FILENO);
        fclose(log);
        if (out < 0 || err < 0) return 1;
        /* Remove LaunchServices additions too: restore exactly the old exec environment. */
        NSMutableArray *keys = [NSMutableArray array];
        for (char **e = *_NSGetEnviron(); *e; ++e) {
            NSString *entry = @(*e); NSRange equal = [entry rangeOfString:@"="];
            if (equal.location != NSNotFound) [keys addObject:[entry substringToIndex:equal.location]];
        }
        for (NSString *key in keys) unsetenv(key.UTF8String);
        for (NSString *key in env) if (setenv(key.UTF8String, [env[key] UTF8String], 1)) return 1;
        fprintf(stderr, "[launcher] app bootstrap: work %s\n", [p[@"work"] UTF8String]);
        return 0;
    }
}
