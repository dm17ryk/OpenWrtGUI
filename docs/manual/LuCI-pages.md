# LuCI pages

Some things a router can do have no screen in OpenWrtGUI yet. For those, the app opens the router's own
LuCI page inside its window, already logged in, so you never type the router's password. The app's look does
not apply inside the page: it is LuCI as the router serves it.

![LuCI page](https://raw.githubusercontent.com/wiki/dm17ryk/OpenWrtGUI/screenshots/luci-page.png)

## Which pages open here

The app reads the router's LuCI menu and access files when it connects. The **LuCI pages** card on the router's
overview lists every page with its LuCI package and where it sits in LuCI's menu ("Network › DHCP"). A page
that has a screen here (Network › Wireless is the Wi-Fi screen) links to that screen. A page with **no screen
here yet** has an **Open in LuCI** button. The same pages are in the **LuCI pages** list next to the router's
section links on every router screen. Two pages with the same name in the same menu (Status › Firewall for
iptables and for nftables) carry their LuCI path name in brackets; LuCI shows only the one the router supports.

## Opening a page

Opening a page makes a LuCI session on the router over SSH, allowed to touch only what that page needs (from the
router's own access files), and shows LuCI through an SSH tunnel. Nothing listens on the network for it: the
page is served on this PC only and only the app's own tab can open it. Changes you save in LuCI skip the app's
preview and its 60 s rollback; LuCI applies them with its own rollback.

## Read-only during a run

While Bench Guard sees a harness run, a page opens with a read-only session: LuCI shows it but cannot save. A
page that is open when a run starts switches to read-only within a few seconds and stays read-only until you
close it. If the app cannot make the read-only session (the SSH link dropped), it closes the page instead.

## Changed via LuCI

The app reads the router's whole configuration when the page opens and again every 5 seconds while it is
open, and lists every option that changed since you opened it, with the value before and after. Wi-Fi keys and
passwords show as hidden. The app cannot preview what LuCI will change, only show it afterwards.

## Session end

**Close and end session** ends the LuCI session on the router and shows the final list of changes. Leaving the
page does the same. A page nobody uses for 5 minutes closes by itself. The audit log records when the page
opened and closed and which options changed.
