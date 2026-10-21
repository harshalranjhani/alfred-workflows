// Renders the workflow, result and app icons from SF Symbols: swift icons.swift <workflow dir> <iconset dir>
import AppKit

func color(_ hex: UInt32) -> NSColor {
    NSColor(srgbRed: CGFloat(hex >> 16 & 0xff) / 255, green: CGFloat(hex >> 8 & 0xff) / 255, blue: CGFloat(hex & 0xff) / 255, alpha: 1)
}

func render(_ symbol: String, _ top: UInt32, _ bottom: UInt32, size: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: size, pixelsHigh: size, bitsPerSample: 8, samplesPerPixel: 4,
                               hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    let s = CGFloat(size), tile = NSRect(x: s * 0.09, y: s * 0.09, width: s * 0.82, height: s * 0.82)
    let shape = NSBezierPath(roundedRect: tile, xRadius: tile.width * 0.225, yRadius: tile.width * 0.225)
    let shadow = NSShadow()
    shadow.shadowColor = NSColor.black.withAlphaComponent(0.25)
    shadow.shadowBlurRadius = s * 0.025
    shadow.shadowOffset = NSSize(width: 0, height: -s * 0.01)
    shadow.set()
    color(bottom).setFill()
    shape.fill()
    NSShadow().set()
    NSGradient(starting: color(top), ending: color(bottom))!.draw(in: shape, angle: -90)
    let config = NSImage.SymbolConfiguration(pointSize: s * 0.36, weight: .semibold).applying(.init(paletteColors: [.white]))
    let image = NSImage(systemSymbolName: symbol, accessibilityDescription: nil)!.withSymbolConfiguration(config)!
    image.draw(in: NSRect(x: (s - image.size.width) / 2, y: (s - image.size.height) / 2, width: image.size.width, height: image.size.height))
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

let workflow = URL(fileURLWithPath: CommandLine.arguments[1]), iconset = URL(fileURLWithPath: CommandLine.arguments[2])
let icons: [String: (String, UInt32, UInt32)] = [
    "zoom": ("video.fill", 0x4A9BFF, 0x0B5CFF),
    "meet": ("video.fill", 0x3DBE63, 0x188038),
    "teams": ("video.fill", 0x8B92F0, 0x4B53BC),
    "video": ("video.fill", 0x3CC4DA, 0x0A84A0),
    "event": ("calendar", 0x9A9AA0, 0x5E5E63),
    "now": ("dot.radiowaves.left.and.right", 0xFF5F57, 0xD70015),
    "bell": ("bell.fill", 0xFFB340, 0xF07800),
    "bell-off": ("bell.slash.fill", 0x9A9AA0, 0x5E5E63),
    "check": ("checkmark", 0x4CD964, 0x248A3D),
    "lock": ("lock.fill", 0x5AC8FA, 0x0A6FD8),
    "clock": ("hourglass", 0xC774F5, 0x8E44AD),
    "power": ("power", 0x636366, 0x2C2C2E),
    "search": ("magnifyingglass", 0x9A9AA0, 0x5E5E63),
]
let app: (String, UInt32, UInt32) = ("calendar.badge.clock", 0x7D7BFF, 0x3A38C8)
try FileManager.default.createDirectory(at: workflow.appendingPathComponent("icons"), withIntermediateDirectories: true)
try FileManager.default.createDirectory(at: iconset, withIntermediateDirectories: true)
for (name, (symbol, top, bottom)) in icons {
    try render(symbol, top, bottom, size: 256).write(to: workflow.appendingPathComponent("icons/\(name).png"))
}
try render(app.0, app.1, app.2, size: 512).write(to: workflow.appendingPathComponent("icon.png"))
for size in [16, 32, 128, 256, 512] {
    try render(app.0, app.1, app.2, size: size).write(to: iconset.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(app.0, app.1, app.2, size: size * 2).write(to: iconset.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
