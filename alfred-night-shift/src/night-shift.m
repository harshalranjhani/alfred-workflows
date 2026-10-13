#import <Foundation/Foundation.h>
#import <dlfcn.h>
#import <math.h>

// Private CoreBrightness ABI. Recheck this layout if a future macOS changes it.
typedef struct {
    BOOL active, enabled, sunSchedulePermitted;
    int mode;
    struct { int fromHour, fromMinute, toHour, toMinute; } schedule;
    unsigned long long disableFlags;
    BOOL available;
} BlueLightStatus;
@interface NSObject (NightShift)
- (BOOL)getBlueLightStatus:(BlueLightStatus *)status;
- (BOOL)getStrength:(float *)strength;
- (BOOL)setEnabled:(BOOL)enabled;
- (BOOL)setStrength:(float)strength commit:(BOOL)commit;
@end

static void json(id value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
}
static NSDictionary *item(NSString *title, NSString *subtitle, NSString *arg) {
    return @{ @"title": title, @"subtitle": subtitle, @"arg": arg ?: @"", @"valid": @(arg != nil) };
}
static int fail(NSString *message, BOOL filter) {
    if (filter) json(@{@"items": @[item(@"Night Shift unavailable", message, nil)]});
    else { fprintf(stderr, "%s\n", message.UTF8String); puts(message.UTF8String); }
    return filter ? 0 : 1;
}
static BOOL percent(NSString *query, int *value) {
    if (!query.length || [query rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789"] invertedSet]].location != NSNotFound) return NO;
    if (query.length > 3) return NO;
    *value = query.intValue;
    return *value <= 100;
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSString *mode = argc > 1 ? @(argv[1]) : @"status";
        BOOL filter = [mode isEqual:@"filter"];
        NSString *query = argc > 2 ? [@(argv[2]) stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet].lowercaseString : @"";
        int warmth = 0;
        BOOL numeric = percent(query, &warmth);
        BOOL toggle = !query.length || [query isEqual:@"toggle"];
        BOOL on = [query isEqual:@"on"], off = [query isEqual:@"off"];
        if (![mode isEqual:@"status"] && !filter && ![mode isEqual:@"apply"])
            return fail(@"Usage: night-shift status | filter [on|off|toggle|0–100] | apply [on|off|toggle|0–100]", NO);
        if (!toggle && !on && !off && !numeric)
            return fail(@"Use on, off, toggle, or a whole number from 0 to 100.", filter);
        if (!dlopen("/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness", RTLD_LAZY))
            return fail(@"Cannot load macOS CoreBrightness.", filter);
        id client = [[NSClassFromString(@"CBBlueLightClient") alloc] init];
        for (NSString *selector in @[@"getBlueLightStatus:", @"getStrength:", @"setEnabled:", @"setStrength:commit:"]) {
            if (![client respondsToSelector:NSSelectorFromString(selector)])
                return fail(@"This macOS version does not expose the required Night Shift controls.", filter);
        }
        BlueLightStatus status = {0};
        float strength = 0;
        if (![client getBlueLightStatus:&status] || ![client getStrength:&strength] || !isfinite(strength) || strength < 0 || strength > 1)
            return fail(@"Unable to read Night Shift. Check Displays in System Settings.", filter);
        if ([mode isEqual:@"status"]) {
            json(@{@"enabled": @(status.enabled), @"strength": @(strength), @"warmth": @(lroundf(strength * 100)), @"scheduleMode": @(status.mode)});
            return 0;
        }
        NSString *summary = [NSString stringWithFormat:@"Currently %@ · Warmth %ld%%", status.enabled ? @"on" : @"off", lroundf(strength * 100)];
        BOOL target = toggle ? !status.enabled : !off;
        NSString *title = numeric ? [NSString stringWithFormat:@"Turn on Night Shift at %d%% warmth", warmth] : [NSString stringWithFormat:@"Turn %@ Night Shift", target ? @"on" : @"off"];
        if (filter) {
            NSMutableArray *items = [NSMutableArray arrayWithObject:item(title, summary, toggle ? @"toggle" : query)];
            if (!query.length) {
                [items addObject:item(@"Set warmth…", @"Type night 0–100 · 0 = least warm, 100 = warmest", nil)];
                for (NSNumber *preset in @[@25, @50, @75, @100])
                    [items addObject:item([NSString stringWithFormat:@"Night Shift · %@%% warmth", preset], @"Apply temperature and turn on Night Shift", preset.stringValue)];
            }
            json(@{@"items": items});
            return 0;
        }
        if (numeric && ![client setStrength:warmth / 100.0f commit:YES])
            return fail(@"macOS could not change Night Shift warmth.", NO);
        if (![client setEnabled:target])
            return fail(@"macOS could not change Night Shift state.", NO);
        // Allow the service to persist the change before this short-lived process exits.
        [NSThread sleepForTimeInterval:0.2];
        puts((numeric ? [NSString stringWithFormat:@"Night Shift on · Warmth %d%%", warmth] : [NSString stringWithFormat:@"Night Shift %@", target ? @"on" : @"off"]).UTF8String);
    }
    return 0;
}
