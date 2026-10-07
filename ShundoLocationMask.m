#import <CoreLocation/CoreLocation.h>
#import <Foundation/Foundation.h>
#import <dlfcn.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <os/log.h>

typedef BOOL (*ShundoBoolGetter)(id, SEL);
typedef id (*ShundoObjectGetter)(id, SEL);

static ShundoBoolGetter ShundoPreviousSimulatedGetter = NULL;
static ShundoObjectGetter ShundoPreviousSourceGetter = NULL;
static NSUInteger ShundoSourceCallCount = 0;

static BOOL ShundoReturnFalse(id object, SEL selector) {
    return NO;
}

static void ShundoLogImplementation(const char *label, IMP implementation) {
    Dl_info info = {0};
    const char *image = "unknown";
    const char *symbol = "unknown";
    if (implementation != NULL && dladdr((const void *)implementation, &info) != 0) {
        image = info.dli_fname ?: "unknown";
        symbol = info.dli_sname ?: "unknown";
    }
    os_log_with_type(
        OS_LOG_DEFAULT,
        OS_LOG_TYPE_DEFAULT,
        "SHUNDO_LOCATION_IMP label=%{public}s image=%{public}s symbol=%{public}s address=%{public}p",
        label,
        image,
        symbol,
        implementation
    );
}

static id ShundoSourceInformation(id location, SEL selector) {
    id sourceInformation = ShundoPreviousSourceGetter != NULL
        ? ShundoPreviousSourceGetter(location, selector)
        : nil;
    SEL simulatedSelector = NSSelectorFromString(@"isSimulatedBySoftware");
    BOOL previousResult = NO;
    BOOL exposedResult = NO;
    if (sourceInformation != nil) {
        if (ShundoPreviousSimulatedGetter != NULL) {
            previousResult = ShundoPreviousSimulatedGetter(sourceInformation, simulatedSelector);
        }
        exposedResult = ((ShundoBoolGetter)objc_msgSend)(sourceInformation, simulatedSelector);
    }
    ShundoSourceCallCount += 1;
    if (ShundoSourceCallCount <= 12 || ShundoSourceCallCount % 100 == 0) {
        os_log_with_type(
            OS_LOG_DEFAULT,
            OS_LOG_TYPE_DEFAULT,
            "SHUNDO_LOCATION_SOURCE call=%{public}lu present=%{public}d previousResult=%{public}d exposedResult=%{public}d",
            (unsigned long)ShundoSourceCallCount,
            sourceInformation != nil,
            previousResult,
            exposedResult
        );
    }
    return sourceInformation;
}

static BOOL ShundoApplyLocationMask(void) {
    Class sourceClass = NSClassFromString(@"CLLocationSourceInformation");
    SEL simulatedSelector = NSSelectorFromString(@"isSimulatedBySoftware");
    Method simulatedMethod = class_getInstanceMethod(sourceClass, simulatedSelector);
    Method sourceMethod = class_getInstanceMethod(
        [CLLocation class],
        NSSelectorFromString(@"sourceInformation")
    );
    if (simulatedMethod == NULL || sourceMethod == NULL) {
        os_log_with_type(OS_LOG_DEFAULT, OS_LOG_TYPE_ERROR, "SHUNDO_LOCATION_MASK_FAILED missingMethod");
        return NO;
    }

    IMP simulatedImplementation = method_getImplementation(simulatedMethod);
    IMP sourceImplementation = method_getImplementation(sourceMethod);
    ShundoLogImplementation("simulated-before", simulatedImplementation);
    ShundoLogImplementation("source-before", sourceImplementation);

    if (simulatedImplementation != (IMP)ShundoReturnFalse) {
        if (ShundoPreviousSimulatedGetter == NULL) {
            ShundoPreviousSimulatedGetter = (ShundoBoolGetter)simulatedImplementation;
        }
        method_setImplementation(simulatedMethod, (IMP)ShundoReturnFalse);
    }
    if (sourceImplementation != (IMP)ShundoSourceInformation) {
        if (ShundoPreviousSourceGetter == NULL) {
            ShundoPreviousSourceGetter = (ShundoObjectGetter)sourceImplementation;
        }
        method_setImplementation(sourceMethod, (IMP)ShundoSourceInformation);
    }

    ShundoLogImplementation("simulated-after", method_getImplementation(simulatedMethod));
    ShundoLogImplementation("source-after", method_getImplementation(sourceMethod));
    os_log_with_type(OS_LOG_DEFAULT, OS_LOG_TYPE_DEFAULT, "SHUNDO_LOCATION_MASK_READY");
    return YES;
}

__attribute__((constructor))
static void ShundoInstallLocationMask(void) {
    ShundoApplyLocationMask();
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 3 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        ShundoApplyLocationMask();
    });
}
