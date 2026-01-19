import xbmc

def wait_for_modal_to_close(timeout_ms=30000):
    waited = 0
    step = 200

    while waited < timeout_ms:
        if not xbmc.getCondVisibility("Window.IsActive(DialogConfirm.xml)") and \
           not xbmc.getCondVisibility("Window.IsActive(DialogYesNo.xml)"):
            return True
        xbmc.sleep(step)
        waited += step

    return False
