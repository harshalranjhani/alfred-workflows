#import <AppKit/AppKit.h>
#import <EventKit/EventKit.h>

// One binary, three roles: Alfred's list/action commands, and the LaunchAgent that
// owns calendar access, keeps events.json fresh, and shows reminder toasts.
static NSString *const kID = @"local.harshal.meetings";
static NSString *const kPreview = @"local.harshal.meetings.preview";
static const CGFloat kToastW = 372, kToastH = 84;

static NSString *cacheDir(void) {
    NSString *dir = NSProcessInfo.processInfo.environment[@"MEETINGS_CACHE_DIR"]; // tests use a fake cache
    return dir ?: [NSHomeDirectory() stringByAppendingPathComponent:@"Library/Caches/local.harshal.meetings"];
}
static NSString *cachePath(void) { return [cacheDir() stringByAppendingPathComponent:@"events.json"]; }
static NSString *agentPlist(void) { return [NSHomeDirectory() stringByAppendingFormat:@"/Library/LaunchAgents/%@.plist", kID]; }
static NSString *exePath(void) { return NSBundle.mainBundle.executablePath; }
static NSString *iconPath(NSString *name) {
    return [NSBundle.mainBundle.bundlePath.stringByDeletingLastPathComponent stringByAppendingFormat:@"/icons/%@.png", name];
}
static NSInteger leadMinutes(void) {
    CFPreferencesAppSynchronize((__bridge CFStringRef)kID); // pick up `mt remind` changes made by another process
    id lead = [NSUserDefaults.standardUserDefaults objectForKey:@"lead"];
    return lead ? [lead integerValue] : 30;
}

#pragma mark - Event data

static NSString *trimLink(NSString *link) {
    return [link stringByTrimmingCharactersInSet:[NSCharacterSet characterSetWithCharactersInString:@".,;:)]}>'\""]];
}
// Returns provider, icon and link for the first video-call URL in the given texts.
static NSDictionary *findLink(NSString *url, NSString *location, NSString *notes) {
    NSString *all = [@[url ?: @"", location ?: @"", notes ?: @""] componentsJoinedByString:@"\n"];
    NSArray *providers = @[
        @[@"Zoom", @"zoom", @"https://[\\w.-]*zoom\\.us/(?:j|my|w|s)/[^\\s<>\"']+"],
        @[@"Google Meet", @"meet", @"https://meet\\.google\\.com/[a-z]{3}-[a-z]{4}-[a-z]{3}"],
        @[@"Microsoft Teams", @"teams", @"https://teams\\.(?:microsoft|live)\\.com/(?:l/meetup-join|meet)/[^\\s<>\"']+"],
        @[@"Webex", @"video", @"https://[\\w.-]*webex\\.com/[^\\s<>\"']+"],
    ];
    for (NSArray *p in providers) {
        NSRange r = [all rangeOfString:p[2] options:NSRegularExpressionSearch | NSCaseInsensitiveSearch];
        if (r.location != NSNotFound) return @{@"provider": p[0], @"icon": p[1], @"link": trimLink([all substringWithRange:r])};
    }
    // Any other web link set as the event URL or location (notes are too noisy for this).
    for (NSString *text in @[url ?: @"", location ?: @""]) {
        NSRange r = [text rangeOfString:@"https?://[^\\s<>\"']+" options:NSRegularExpressionSearch];
        if (r.location != NSNotFound) {
            NSString *link = trimLink([text substringWithRange:r]);
            NSString *host = [[NSURL URLWithString:link].host stringByReplacingOccurrencesOfString:@"www." withString:@""];
            return @{@"provider": host ?: @"Link", @"icon": @"video", @"link": link};
        }
    }
    return nil;
}
static NSString *calendarURL(EKEvent *e) {
    NSDateFormatter *f = [NSDateFormatter new];
    f.locale = [NSLocale localeWithLocaleIdentifier:@"en_US_POSIX"];
    f.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    f.dateFormat = @"yyyyMMdd'T'HHmmss'Z'";
    NSString *uid = [e.calendarItemIdentifier stringByAddingPercentEncodingWithAllowedCharacters:NSCharacterSet.URLPathAllowedCharacterSet];
    return [NSString stringWithFormat:@"ical://ekevent/%@/%@?method=show&options=more", [f stringFromDate:e.startDate], uid];
}
static NSArray *upcoming(EKEventStore *store) {
    NSDate *now = NSDate.date;
    NSPredicate *range = [store predicateForEventsWithStartDate:now endDate:[now dateByAddingTimeInterval:7 * 86400] calendars:nil];
    NSMutableArray *events = [NSMutableArray array];
    for (EKEvent *e in [[store eventsMatchingPredicate:range] sortedArrayUsingSelector:@selector(compareStartDateWithEvent:)]) {
        if (e.allDay || e.status == EKEventStatusCanceled || [e.endDate compare:now] != NSOrderedDescending) continue;
        BOOL declined = NO;
        for (EKParticipant *a in e.attendees) declined |= a.isCurrentUser && a.participantStatus == EKParticipantStatusDeclined;
        if (declined) continue;
        NSString *location = [e.location containsString:@"://"] ? @"" : (e.location ?: @"");
        NSMutableDictionary *d = [@{
            @"title": e.title.length ? e.title : @"Untitled event",
            @"start": @(floor(e.startDate.timeIntervalSince1970)), @"end": @(floor(e.endDate.timeIntervalSince1970)),
            @"calendar": e.calendar.title ?: @"", @"location": location, @"ical": calendarURL(e),
            @"key": [NSString stringWithFormat:@"%@@%.0f", e.calendarItemIdentifier, e.startDate.timeIntervalSince1970],
        } mutableCopy];
        [d addEntriesFromDictionary:findLink(e.URL.absoluteString, e.location, e.notes) ?: @{}];
        [events addObject:d];
    }
    return events;
}

#pragma mark - Formatting

static NSString *duration(double seconds) {
    long minutes = (long)ceil(seconds / 60);
    if (minutes < 60) return [NSString stringWithFormat:@"%ld min", minutes];
    if (minutes < 24 * 60) return minutes % 60 ? [NSString stringWithFormat:@"%ldh %ldm", minutes / 60, minutes % 60]
                                               : [NSString stringWithFormat:@"%ldh", minutes / 60];
    long days = (minutes + 12 * 60) / (24 * 60);
    return [NSString stringWithFormat:@"%ld day%@", days, days == 1 ? @"" : @"s"];
}
static NSString *relative(NSDictionary *e, double now) {
    double start = [e[@"start"] doubleValue], end = [e[@"end"] doubleValue];
    if (start <= now) return [NSString stringWithFormat:@"Now · ends in %@", duration(end - now)];
    if (start - now < 60) return @"Starting now";
    return [@"In " stringByAppendingString:duration(start - now)];
}
static NSString *timeRange(NSDictionary *e) {
    NSDateFormatter *f = [NSDateFormatter new];
    f.dateStyle = NSDateFormatterNoStyle;
    f.timeStyle = NSDateFormatterShortStyle;
    return [NSString stringWithFormat:@"%@ – %@", [f stringFromDate:[NSDate dateWithTimeIntervalSince1970:[e[@"start"] doubleValue]]],
                                      [f stringFromDate:[NSDate dateWithTimeIntervalSince1970:[e[@"end"] doubleValue]]]];
}
static NSString *dayLabel(NSDictionary *e) {
    NSDate *d = [NSDate dateWithTimeIntervalSince1970:[e[@"start"] doubleValue]];
    if ([NSCalendar.currentCalendar isDateInToday:d]) return @"Today";
    if ([NSCalendar.currentCalendar isDateInTomorrow:d]) return @"Tomorrow";
    NSDateFormatter *f = [NSDateFormatter new];
    [f setLocalizedDateFormatFromTemplate:@"EEEdMMM"];
    return [f stringFromDate:d];
}
static NSString *joined(NSArray *parts) {
    return [[parts filteredArrayUsingPredicate:[NSPredicate predicateWithFormat:@"length > 0"]] componentsJoinedByString:@" · "];
}

#pragma mark - LaunchAgent

static void launchctl(NSArray *args) {
    NSTask *t = [NSTask new];
    t.executableURL = [NSURL fileURLWithPath:@"/bin/launchctl"];
    t.arguments = args;
    t.standardOutput = t.standardError = NSFileHandle.fileHandleWithNullDevice;
    if ([t launchAndReturnError:nil]) [t waitUntilExit];
}
static NSString *guiDomain(void) { return [NSString stringWithFormat:@"gui/%u", getuid()]; }
static void ensureAgent(void) {
    NSArray *program = @[exePath(), @"agent"];
    if ([[NSDictionary dictionaryWithContentsOfFile:agentPlist()][@"ProgramArguments"] isEqual:program]) return;
    NSFileManager *fm = NSFileManager.defaultManager;
    [fm createDirectoryAtPath:agentPlist().stringByDeletingLastPathComponent withIntermediateDirectories:YES attributes:nil error:nil];
    [fm createDirectoryAtPath:cacheDir() withIntermediateDirectories:YES attributes:nil error:nil];
    launchctl(@[@"bootout", [NSString stringWithFormat:@"%@/%@", guiDomain(), kID]]);
    [@{@"Label": kID, @"ProgramArguments": program, @"RunAtLoad": @YES, @"KeepAlive": @YES,
       @"ProcessType": @"Interactive", @"LimitLoadToSessionType": @"Aqua",
       @"StandardErrorPath": [cacheDir() stringByAppendingPathComponent:@"agent.log"]} writeToFile:agentPlist() atomically:YES];
    launchctl(@[@"bootstrap", guiDomain(), agentPlist()]);
}
static void removeAgent(void) {
    [NSFileManager.defaultManager removeItemAtPath:agentPlist() error:nil];
    [NSFileManager.defaultManager removeItemAtPath:cacheDir() error:nil];
    launchctl(@[@"bootout", [NSString stringWithFormat:@"%@/%@", guiDomain(), kID]]); // ends this process when run by the agent
}

#pragma mark - Alfred

static void printJSON(id value) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
}
static NSMutableDictionary *item(NSString *title, NSString *subtitle, NSString *arg, NSString *icon) {
    return [@{@"title": title, @"subtitle": subtitle, @"arg": arg ?: @"", @"valid": arg ? @YES : @NO,
              @"icon": @{@"path": [NSString stringWithFormat:@"icons/%@.png", icon]}} mutableCopy];
}
static BOOL validMinutes(NSString *s, NSInteger *minutes) {
    if (!s.length || s.length > 3 || [s rangeOfCharacterFromSet:NSCharacterSet.decimalDigitCharacterSet.invertedSet].location != NSNotFound) return NO;
    *minutes = s.integerValue;
    return *minutes >= 1 && *minutes <= 240;
}
static NSArray *remindItems(NSString *rest) {
    NSInteger lead = leadMinutes(), minutes = 0;
    if ([rest isEqualToString:@"off"]) rest = @"";
    else if (rest.length) {
        if (!validMinutes(rest, &minutes)) return @[item(@"Enter minutes from 1 to 240", @"For example: mt remind 15", nil, @"bell")];
        return @[item([NSString stringWithFormat:@"Remind me %ld min before meetings", (long)minutes],
                      minutes == lead ? @"This is the current setting" : @"Press Return to save",
                      [NSString stringWithFormat:@"remind:%ld", (long)minutes], minutes == lead ? @"check" : @"bell")];
    }
    NSMutableArray *items = [NSMutableArray array];
    for (NSNumber *n in @[@5, @10, @15, @30, @60]) {
        BOOL current = n.integerValue == lead;
        [items addObject:item([NSString stringWithFormat:@"%@ minutes before", n],
                              current ? @"Current setting · type a number for a custom time, e.g. mt remind 45" : @"Press Return to use this lead time",
                              [NSString stringWithFormat:@"remind:%@", n], current ? @"check" : @"bell")];
    }
    if (lead > 0 && ![@[@5, @10, @15, @30, @60] containsObject:@(lead)])
        [items insertObject:item([NSString stringWithFormat:@"%ld minutes before", (long)lead], @"Current setting", nil, @"check") atIndex:0];
    [items addObject:item(lead ? @"Turn reminders off" : @"Reminders are off", lead ? @"The meetings list keeps working" : @"Pick a lead time above to turn them back on",
                          lead ? @"remind:0" : nil, @"bell-off")];
    [items addObject:item(@"Preview a reminder", @"Shows the reminder card for your next meeting", @"preview", @"now")];
    [items addObject:item(@"Remove background agent", @"Do this before deleting the workflow · running mt sets it up again", @"uninstall", @"power")];
    return items;
}
static NSDictionary *eventItem(NSDictionary *e, double now) {
    NSString *link = e[@"link"];
    BOOL live = [e[@"start"] doubleValue] <= now, soon = [e[@"start"] doubleValue] - now < 12 * 3600;
    NSString *when = live ? relative(e, now) : joined(@[[NSString stringWithFormat:@"%@ %@", dayLabel(e), timeRange(e)], soon ? relative(e, now) : @""]);
    NSString *where = link ? e[@"provider"] : e[@"location"];
    NSMutableDictionary *it = item(e[@"title"], joined(@[when, where ?: @"", e[@"calendar"]]), link ?: e[@"ical"],
                                   live ? @"now" : (link ? e[@"icon"] : @"event"));
    it[@"mods"] = @{
        @"cmd": @{@"arg": e[@"ical"], @"subtitle": @"Open in Calendar", @"valid": @YES},
        @"alt": link ? @{@"arg": link, @"subtitle": [@"Copy meeting link · " stringByAppendingString:link], @"valid": @YES}
                     : @{@"subtitle": @"This event has no meeting link", @"valid": @NO},
    };
    it[@"text"] = @{@"copy": link ?: e[@"title"], @"largetype": joined(@[e[@"title"], timeRange(e), where ?: @""])};
    return it;
}
static int list(NSString *query) {
    NSString *q = [query stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
    if ([q.lowercaseString hasPrefix:@"remind"]) {
        printJSON(@{@"items": remindItems([[q substringFromIndex:6].lowercaseString stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceCharacterSet])});
        return 0;
    }
    if (!NSProcessInfo.processInfo.environment[@"MEETINGS_CACHE_DIR"]) ensureAgent();
    NSDictionary *cache = [NSJSONSerialization JSONObjectWithData:[NSData dataWithContentsOfFile:cachePath()] ?: NSData.data options:0 error:nil];
    if ([cache[@"status"] isEqual:@"denied"]) {
        printJSON(@{@"items": @[item(@"Calendar access needed", @"Press Return, then turn on Full Access for “Meetings” under Calendars",
                                     @"x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars", @"lock")]});
        return 0;
    }
    if (![cache[@"status"] isEqual:@"granted"]) {
        printJSON(@{@"rerun": @1, @"items": @[item(@"Setting up Meetings…", @"Click Allow when macOS asks to give “Meetings” access to your calendar", nil, @"clock")]});
        return 0;
    }
    double now = NSDate.date.timeIntervalSince1970;
    NSArray *terms = [q.lowercaseString componentsSeparatedByCharactersInSet:NSCharacterSet.whitespaceCharacterSet];
    NSMutableArray *items = [NSMutableArray array];
    for (NSDictionary *e in cache[@"events"]) {
        if ([e[@"end"] doubleValue] <= now) continue;
        NSString *haystack = [joined(@[e[@"title"], e[@"calendar"], e[@"provider"] ?: @"", e[@"location"]]) lowercaseString];
        BOOL match = YES;
        for (NSString *t in terms) match &= !t.length || [haystack containsString:t];
        if (match) [items addObject:eventItem(e, now)];
    }
    if (!items.count) [items addObject:q.length ? item(@"No matching meetings", [NSString stringWithFormat:@"Nothing in the next 7 days matches “%@”", q], nil, @"search")
                                                : item(@"No meetings in the next 7 days", @"Your calendar is clear", nil, @"check")];
    if (!q.length) {
        NSInteger lead = leadMinutes();
        NSMutableDictionary *footer = item(lead ? [NSString stringWithFormat:@"Reminders %ld min before meetings", (long)lead] : @"Reminders are off",
                                           @"Press Return to change", nil, lead ? @"bell" : @"bell-off");
        footer[@"autocomplete"] = @"remind ";
        [items addObject:footer];
    }
    printJSON(@{@"skipknowledge": @YES, @"items": items});
    return 0;
}
static int act(NSString *arg) {
    NSInteger minutes = 0;
    if ([arg hasPrefix:@"remind:"]) {
        NSString *value = [arg substringFromIndex:7];
        if (![value isEqualToString:@"0"] && !validMinutes(value, &minutes)) return 1;
        [NSUserDefaults.standardUserDefaults setInteger:minutes forKey:@"lead"];
        CFPreferencesAppSynchronize((__bridge CFStringRef)kID);
        ensureAgent();
        puts(minutes ? [NSString stringWithFormat:@"You'll be reminded %ld minutes before meetings", (long)minutes].UTF8String : "Meeting reminders are off");
        return 0;
    }
    if ([arg isEqualToString:@"preview"]) {
        ensureAgent();
        [NSDistributedNotificationCenter.defaultCenter postNotificationName:kPreview object:nil userInfo:nil deliverImmediately:YES];
        return 0;
    }
    if ([arg isEqualToString:@"uninstall"]) {
        removeAgent();
        puts("Background agent removed");
        return 0;
    }
    NSURL *url = [NSURL URLWithString:arg];
    if (![@[@"http", @"https", @"ical", @"x-apple.systempreferences"] containsObject:url.scheme.lowercaseString]) return 1;
    return [NSWorkspace.sharedWorkspace openURL:url] ? 0 : 1;
}

#pragma mark - Toast

@interface ToastView : NSVisualEffectView
@property (copy) void (^onHover)(BOOL inside);
@property (copy) void (^onClick)(void);
@end
@implementation ToastView
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; }
- (void)mouseDown:(NSEvent *)event {}
- (void)mouseUp:(NSEvent *)event { self.onClick(); }
- (void)mouseEntered:(NSEvent *)event { self.onHover(YES); }
- (void)mouseExited:(NSEvent *)event { self.onHover(NO); }
@end

@interface ToastButton : NSButton
@property (copy) void (^run)(void);
@end
@implementation ToastButton
- (BOOL)acceptsFirstMouse:(NSEvent *)event { return YES; } // the agent is never the active app
- (void)fire { self.run(); }
@end

@interface Agent : NSObject
@property EKEventStore *store;
@property BOOL granted;
@property NSArray *events;
@property NSDate *built;
@property NSMutableArray<NSPanel *> *toasts;
@end

@implementation Agent
- (void)tick {
    NSDate *modified = [NSFileManager.defaultManager attributesOfItemAtPath:exePath() error:nil].fileModificationDate;
    if (!modified) { removeAgent(); exit(0); } // workflow was deleted
    if (![modified isEqualToDate:self.built]) exit(0); // workflow was updated; launchd restarts the new binary
    EKAuthorizationStatus status = [EKEventStore authorizationStatusForEntityType:EKEntityTypeEvent];
    if (status != EKAuthorizationStatusFullAccess) {
        [self write:@{@"status": status == EKAuthorizationStatusNotDetermined ? @"pending" : @"denied", @"events": @[]}];
        return;
    }
    if (!self.granted) { self.store = [EKEventStore new]; self.granted = YES; } // a store made before the grant stays empty
    self.events = upcoming(self.store);
    [self write:@{@"status": @"granted", @"events": self.events}];

    NSInteger lead = leadMinutes();
    double now = NSDate.date.timeIntervalSince1970;
    NSMutableDictionary *done = [[NSUserDefaults.standardUserDefaults dictionaryForKey:@"notified"] mutableCopy] ?: [NSMutableDictionary dictionary];
    for (NSString *key in done.allKeys) if ([done[key] doubleValue] < now - 86400) [done removeObjectForKey:key];
    for (NSDictionary *e in lead > 0 ? self.events : @[]) {
        double start = [e[@"start"] doubleValue];
        if (now >= start - lead * 60 && now < start + 60 && !done[e[@"key"]]) {
            done[e[@"key"]] = e[@"start"];
            [self toast:e];
        }
    }
    [NSUserDefaults.standardUserDefaults setObject:done forKey:@"notified"];
}
- (void)write:(NSDictionary *)cache {
    NSData *data = [NSJSONSerialization dataWithJSONObject:cache options:0 error:nil];
    if ([data isEqualToData:[NSData dataWithContentsOfFile:cachePath()]]) return;
    [NSFileManager.defaultManager createDirectoryAtPath:cacheDir() withIntermediateDirectories:YES attributes:nil error:nil];
    [data writeToFile:cachePath() atomically:YES];
}
- (void)preview {
    double now = NSDate.date.timeIntervalSince1970;
    [self toast:self.events.firstObject ?: @{@"title": @"No upcoming meetings", @"start": @(now + 1800), @"end": @(now + 3600),
                                             @"calendar": @"Reminders look like this", @"location": @"", @"ical": @"ical://"}];
}
- (void)toast:(NSDictionary *)e {
    NSPanel *panel = [[NSPanel alloc] initWithContentRect:NSMakeRect(0, 0, kToastW, kToastH)
                                                styleMask:NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
                                                  backing:NSBackingStoreBuffered defer:NO];
    panel.level = NSStatusWindowLevel;
    panel.opaque = NO;
    panel.backgroundColor = NSColor.clearColor;
    panel.hasShadow = YES;
    panel.releasedWhenClosed = NO;
    panel.hidesOnDeactivate = NO;
    panel.collectionBehavior = NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary |
                               NSWindowCollectionBehaviorStationary | NSWindowCollectionBehaviorIgnoresCycle;
    // Keep reminders out of screen shares and recordings; MEETINGS_CAPTURE allows screenshots for checks.
    panel.sharingType = getenv("MEETINGS_CAPTURE") ? NSWindowSharingReadOnly : NSWindowSharingNone;

    ToastView *view = [[ToastView alloc] initWithFrame:NSMakeRect(0, 0, kToastW, kToastH)];
    view.material = NSVisualEffectMaterialPopover;
    view.blendingMode = NSVisualEffectBlendingModeBehindWindow;
    view.state = NSVisualEffectStateActive;
    NSImage *mask = [NSImage imageWithSize:NSMakeSize(41, 41) flipped:NO drawingHandler:^BOOL(NSRect r) {
        [[NSBezierPath bezierPathWithRoundedRect:r xRadius:18 yRadius:18] fill];
        return YES;
    }];
    mask.capInsets = NSEdgeInsetsMake(20, 20, 20, 20);
    mask.resizingMode = NSImageResizingModeStretch;
    view.maskImage = mask;
    panel.contentView = view;

    NSString *link = e[@"link"];
    NSImageView *icon = [NSImageView imageViewWithImage:[[NSImage alloc] initWithContentsOfFile:iconPath(link ? e[@"icon"] : @"event")] ?: [NSImage new]];
    icon.frame = NSMakeRect(12, 18, 48, 48);
    [view addSubview:icon];
    double now = NSDate.date.timeIntervalSince1970;
    NSArray *lines = @[
        @[e[@"title"], [NSFont boldSystemFontOfSize:13], NSColor.labelColor, @48],
        @[joined(@[relative(e, now), timeRange(e)]), [NSFont systemFontOfSize:11.5], NSColor.secondaryLabelColor, @30],
        @[joined(@[link ? e[@"provider"] : e[@"location"], e[@"calendar"]]), [NSFont systemFontOfSize:11.5], NSColor.secondaryLabelColor, @13],
    ];
    for (NSArray *l in lines) {
        NSTextField *label = [NSTextField labelWithString:l[0]];
        label.font = l[1];
        label.textColor = l[2];
        label.lineBreakMode = NSLineBreakByTruncatingTail;
        label.frame = NSMakeRect(70, [l[3] doubleValue], kToastW - 70 - 92, 18);
        [view addSubview:label];
    }
    __weak Agent *weakSelf = self;
    __weak NSPanel *weakPanel = panel;
    void (^open)(void) = ^{
        [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:link ?: e[@"ical"]]];
        [weakSelf dismiss:weakPanel];
    };
    // Drawn by hand: AppKit greys out tinted buttons in apps that are not active, and the agent never is.
    ToastButton *join = [ToastButton buttonWithTitle:@"" target:nil action:nil];
    join.bordered = NO;
    join.wantsLayer = YES;
    join.layer.backgroundColor = NSColor.controlAccentColor.CGColor;
    join.layer.cornerRadius = 15;
    join.attributedTitle = [[NSAttributedString alloc] initWithString:link ? @"Join" : @"Open"
        attributes:@{NSForegroundColorAttributeName: NSColor.whiteColor, NSFontAttributeName: [NSFont systemFontOfSize:13 weight:NSFontWeightSemibold]}];
    join.frame = NSMakeRect(kToastW - 14 - 72, (kToastH - 30) / 2, 72, 30);
    [view addSubview:join];
    ToastButton *close = [ToastButton buttonWithImage:[NSImage imageWithSystemSymbolName:@"xmark.circle.fill" accessibilityDescription:@"Dismiss"]
                                               target:nil action:nil];
    close.bordered = NO;
    close.contentTintColor = NSColor.secondaryLabelColor;
    close.frame = NSMakeRect(4, kToastH - 22, 18, 18);
    close.hidden = YES;
    [view addSubview:close];
    for (ToastButton *b in @[join, close]) { b.target = b; b.action = @selector(fire); }
    join.run = open;
    close.run = ^{ [weakSelf dismiss:weakPanel]; };

    __block NSTimer *timer = [NSTimer scheduledTimerWithTimeInterval:60 repeats:NO block:^(NSTimer *t) { [weakSelf dismiss:weakPanel]; }];
    view.onClick = open;
    view.onHover = ^(BOOL inside) {
        close.hidden = !inside;
        [timer invalidate];
        if (!inside) timer = [NSTimer scheduledTimerWithTimeInterval:10 repeats:NO block:^(NSTimer *t) { [weakSelf dismiss:weakPanel]; }];
    };
    [view addTrackingArea:[[NSTrackingArea alloc] initWithRect:NSZeroRect
                                                       options:NSTrackingMouseEnteredAndExited | NSTrackingActiveAlways | NSTrackingInVisibleRect
                                                         owner:view userInfo:nil]];

    NSRect screen = NSScreen.screens.firstObject.visibleFrame; // the menu-bar display, like system notifications
    [panel setFrameOrigin:NSMakePoint(NSMaxX(screen) - kToastW + 20, NSMaxY(screen) - 10 - kToastH)];
    panel.alphaValue = 0;
    [panel orderFrontRegardless];
    [self.toasts insertObject:panel atIndex:0];
    [self layout];
    [[NSSound soundNamed:@"Glass"] play];
}
- (void)layout {
    NSRect screen = NSScreen.screens.firstObject.visibleFrame; // the menu-bar display, like system notifications
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
        context.duration = 0.25;
        CGFloat y = NSMaxY(screen) - 10;
        for (NSPanel *p in self.toasts) {
            y -= kToastH;
            [p.animator setFrame:NSMakeRect(NSMaxX(screen) - kToastW - 12, y, kToastW, kToastH) display:YES];
            p.animator.alphaValue = 1;
            y -= 10;
        }
    }];
}
- (void)dismiss:(NSPanel *)panel {
    if (!panel || ![self.toasts containsObject:panel]) return;
    [self.toasts removeObject:panel];
    [NSAnimationContext runAnimationGroup:^(NSAnimationContext *context) {
        context.duration = 0.2;
        panel.animator.alphaValue = 0;
    } completionHandler:^{
        [panel orderOut:nil];
        [self layout];
    }];
}
@end

static int runAgent(void) {
    NSApplication *app = NSApplication.sharedApplication;
    app.activationPolicy = NSApplicationActivationPolicyAccessory;
    Agent *agent = [Agent new];
    agent.toasts = [NSMutableArray array];
    agent.built = [NSFileManager.defaultManager attributesOfItemAtPath:exePath() error:nil].fileModificationDate;
    agent.granted = [EKEventStore authorizationStatusForEntityType:EKEntityTypeEvent] == EKAuthorizationStatusFullAccess;
    agent.store = [EKEventStore new];
    [agent.store requestFullAccessToEventsWithCompletion:^(BOOL granted, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{ [agent tick]; });
    }];
    [agent tick];
    NSTimer *timer = [NSTimer scheduledTimerWithTimeInterval:20 repeats:YES block:^(NSTimer *t) { [agent tick]; }];
    timer.tolerance = 5;
    [NSNotificationCenter.defaultCenter addObserverForName:EKEventStoreChangedNotification object:nil queue:NSOperationQueue.mainQueue
                                                usingBlock:^(NSNotification *n) { [agent tick]; }];
    [NSWorkspace.sharedWorkspace.notificationCenter addObserverForName:NSWorkspaceDidWakeNotification object:nil queue:NSOperationQueue.mainQueue
                                                            usingBlock:^(NSNotification *n) { [agent tick]; }];
    [NSDistributedNotificationCenter.defaultCenter addObserverForName:kPreview object:nil queue:NSOperationQueue.mainQueue
                                                           usingBlock:^(NSNotification *n) { [agent preview]; }];
    [app run];
    return 0;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSString *mode = argc > 1 ? @(argv[1]) : @"";
        NSString *arg = argc > 2 ? @(argv[2]) : @"";
        if ([mode isEqualToString:@"list"]) return list(arg);
        if ([mode isEqualToString:@"act"]) return act(arg);
        if ([mode isEqualToString:@"agent"]) return runAgent();
        if ([mode isEqualToString:@"link"]) { printJSON(findLink(arg, nil, nil) ?: @{}); return 0; }
        fprintf(stderr, "usage: meetings list [query] | act <arg> | agent | link <text>\n");
        return 2;
    }
}
