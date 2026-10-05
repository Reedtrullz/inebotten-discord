"""Native-rehearsal layout admission under small and asynchronously mapped displays."""
from types import SimpleNamespace

from scripts import check_desktop_lifecycle as rehearsal


def test_rehearsal_waits_for_mapping_inside_available_screen():
    root = SimpleNamespace(width=1, height=1, updates=0)
    root.winfo_screenwidth = lambda: 800
    root.winfo_screenheight = lambda: 640
    root.winfo_width = lambda: root.width
    root.winfo_height = lambda: root.height
    requested = []
    root.geometry = lambda value: requested.append(value)
    def pump(predicate, seconds=4):
        assert not predicate()  # A WM may not have mapped the window yet.
        root.updates += 1
        assert not predicate()
        root.width,root.height = map(int,requested[-1].split('x'))
        root.updates += 1
        assert predicate()
    resize = getattr(rehearsal, 'resize_native_window', None)
    assert resize is not None, 'native geometry currently assumes one update and a fixed desktop size'
    receipt = resize(root,pump)
    assert root.updates == 2
    assert 480 <= root.width < 800
    assert 480 <= root.height < 640
    assert receipt['actual_size']==[root.width,root.height]
    assert receipt['screen_size']==[800,640]
