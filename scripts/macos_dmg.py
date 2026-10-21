"""Render the Mac install canvas and write Finder layout without UI automation."""
from pathlib import Path

APP_LABEL = 'Find Me a Job Setup.app'
GUIDE_LABEL = 'Installation guide.html'
SIZE = (900, 560)
LOCATIONS = {APP_LABEL: (230, 250), 'Applications': (670, 250), GUIDE_LABEL: (94, 460)}


def artwork(destination):
    from PIL import Image, ImageDraw, ImageFont

    destination.mkdir()
    scale = 2
    image = Image.new('RGB', (SIZE[0] * scale, SIZE[1] * scale), '#fbfbf9')
    draw = ImageDraw.Draw(image)
    def font(size, bold=False, title=False):
        path = '/System/Library/Fonts/Supplemental/Futura.ttc' if title else '/System/Library/Fonts/Avenir Next.ttc'
        return ImageFont.truetype(path, size * scale, index=(2 if bold else 0) if title else (2 if bold else 7))
    def text(x, y, wording, size=18, color='#161616', bold=False, title=False):
        draw.text((x * scale, y * scale), wording, font=font(size, bold, title), fill=color)
    def line(points, color, width=1):
        draw.line([(x * scale, y * scale) for x, y in points], fill=color, width=width * scale)
    text(42, 24, 'fmj /', 18, '#1747ee', bold=True, title=True)
    text(735, 31, 'MAC SETUP', 11, '#686868')
    line([(42, 62), (858, 62)], '#b9b9b4')
    text(42, 76, 'Install Find Me a Job', 37, title=True)
    text(42, 139, '1. Drag the app into Applications.', 22, bold=True)
    line([(385, 250), (515, 250)], '#1747ee', 3)
    line([(499, 235), (515, 250), (499, 265)], '#1747ee', 3)
    line([(42, 367), (858, 367)], '#b9b9b4')
    text(180, 391, '2. Open Applications.', 22, bold=True)
    text(180, 430, 'Double-click Find Me a Job Setup to start the wizard.', 18)
    text(180, 468, 'You can eject this disk after the app has finished copying.', 15, '#686868')
    text(180, 508, 'Need help? Open the installation guide on the left.', 15, '#686868')
    # Both sizes let dmgbuild create a Retina-aware TIFF background.
    image.save(destination / ('background' + '@' + '2x.tiff'), dpi=(144, 144))
    image.resize(SIZE, Image.Resampling.LANCZOS).save(destination / 'background.tiff', dpi=(72, 72))
    image.save(destination / 'background-preview.png')

    icon = Image.new('RGBA', (1024, 1024))
    ink = ImageDraw.Draw(icon)
    ink.rounded_rectangle((42, 42, 982, 982), radius=210, fill='#1747ee')
    face = ImageFont.truetype('/System/Library/Fonts/Supplemental/Futura.ttc', 300, index=2)
    ink.text((512, 480), 'fmj/', anchor='mm', font=face, fill='white')
    icon.save(destination / 'setup.icns')
    return destination / 'setup.icns'


def settings(app, guide, assets):
    return {'format': 'UDZO', 'files': [(str(app), APP_LABEL), (str(guide), GUIDE_LABEL)],
            'symlinks': {'Applications': '/Applications'},
            'background': str(assets / 'background.tiff'), 'icon': str(assets / 'setup.icns'),
            'icon_locations': LOCATIONS, 'window_rect': ((140, 120), SIZE),
            'default_view': 'icon-view', 'arrange_by': None, 'icon_size': 96, 'text_size': 13,
            'show_toolbar': False, 'show_sidebar': False, 'show_status_bar': False,
            'show_pathbar': False, 'show_tab_view': False, 'show_icon_preview': False,
            'hide_extensions': [GUIDE_LABEL]}


def package(artifact, app, guide, assets):
    import dmgbuild
    dmgbuild.build_dmg(str(artifact), 'Find Me a Job Setup', settings=settings(app, guide, assets))


def verify(artifact):
    """Inspect the assembled image, then copy and launch the app outside the disk."""
    import json
    import os
    import plistlib
    import shutil
    import subprocess
    import tempfile
    from ds_store import DSStore

    result = subprocess.check_output(['hdiutil', 'attach', '-readonly', '-nobrowse', '-noautoopen', '-plist', str(artifact)])
    mount = next(Path(item['mount-point']) for item in plistlib.loads(result)['system-entities'] if 'mount-point' in item)
    try:
        visible = sorted(item.name for item in mount.iterdir() if not item.name.startswith('.'))
        if visible != sorted([APP_LABEL, 'Applications', GUIDE_LABEL]):
            raise RuntimeError('DMG must show the application, Applications shortcut and installation guide')
        if not (mount / 'Applications').is_symlink() or os.readlink(mount / 'Applications') != '/Applications':
            raise RuntimeError('DMG Applications shortcut is incorrect')
        with DSStore.open(str(mount / '.DS_Store'), 'r') as store:
            positions = {name: store[name]['Iloc'] for name in LOCATIONS}
            if positions != LOCATIONS or store['.']['icvp']['backgroundType'] != 2:
                raise RuntimeError('DMG Finder positions or instruction background are missing')
            if store['.']['icvp']['iconSize'] != 96:
                raise RuntimeError('DMG icon size does not match the install canvas')
        with tempfile.TemporaryDirectory(prefix='fmj-dmg-copy-') as temporary:
            copied = Path(temporary) / APP_LABEL
            shutil.copytree(mount / APP_LABEL, copied, symlinks=True)
            info = plistlib.loads((copied / 'Contents/Info.plist').read_bytes())
            report = Path(temporary) / 'copied-app.json'
            env = dict(os.environ, PATH=os.defpath)
            subprocess.run([str(copied / 'Contents/MacOS' / info['CFBundleExecutable']), '--self-test', str(report)],
                           env=env, check=True, timeout=60)
            smoke = json.loads(report.read_text())
            if smoke.get('status') != 'passed' or not smoke.get('bundled') or smoke.get('installs_executed'):
                raise RuntimeError('Copied application did not launch safely')
        return {'visible_entries': visible, 'applications_target': '/Applications',
                'icon_positions': positions, 'copied_app_smoke': smoke}
    finally:
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
