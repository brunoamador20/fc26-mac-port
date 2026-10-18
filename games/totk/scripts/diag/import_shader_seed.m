// CPU-only diagnostic of the production importer; no game or GPU is started.
#import "totk_shader_seed.h"
int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 3) { fprintf(stderr, "usage: import-shader-seed <bundled-seed> <private-cache>\n"); return 2; }
        NSError *error = nil;
        NSDictionary *result = totk_seed_import(@(argv[1]), @(argv[2]), &error);
        if (!result) { fprintf(stderr, "%s\n", error.localizedDescription.UTF8String); return 1; }
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingSortedKeys error:&error];
        if (!data) return 1;
        puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
        return 0;
    }
}
