//! Opt-in Evermore dialogue mailbox. No controller, combat, or general write API.
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};
use serde::{Deserialize, Serialize};

const MAILBOX: usize = 0x28e0;
const TEXT: usize = 0x1f000;
const CAPACITY: usize = 512;
static SERIAL: AtomicU64 = AtomicU64::new(0);

#[derive(Serialize)]
struct Request<'a> {
    session: &'a str,
    generation: u64,
    request: u16,
    name: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Reply {
    session: String,
    generation: u64,
    request: u16,
    text: Vec<u8>,
}

pub(crate) struct Bridge {
    dir: PathBuf,
    session: String,
    generation: u64,
    active: Option<u16>,
    frame: u64,
}
impl Bridge {
    pub(crate) fn for_rom(rom: &[u8]) -> Option<Self> {
        if rom.get(0x33f000..0x33f010)? != b"EVERMORE-GM-0001" { return None; }
        let dir = PathBuf::from(std::env::var_os("LUNA_EVERMORE_BRIDGE")?);
        if !dir.is_dir() { return None; }
        let time = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_nanos();
        Some(Self { dir, session: format!("{}-{time}-{}", std::process::id(), SERIAL.fetch_add(1, Ordering::Relaxed)),
                    generation: 0, active: None, frame: u64::MAX })
    }
    pub(crate) fn reset(&mut self) {
        self.generation += 1;
        self.active = None;
        self.frame = u64::MAX;
        let _ = std::fs::remove_file(self.dir.join("request.json"));
    }
    pub(crate) fn poll(&mut self, ram: &mut [u8], frame: u64) {
        if self.frame != u64::MAX && frame.wrapping_sub(self.frame) < 6 { return; }
        self.frame = frame;
        if ram.len() < TEXT + CAPACITY { return; }
        let word = |at| u16::from_le_bytes([ram[at], ram[at+1]]);
        if ram[0x22ec] & 0x20 == 0 || word(MAILBOX) != 0x4d47
            || word(MAILBOX+2) != 1 || word(MAILBOX+6) != 1 {
            if self.active.take().is_some() { let _ = std::fs::remove_file(self.dir.join("request.json")); }
            return;
        }
        let request = word(MAILBOX+4);
        if self.active != Some(request) {
            self.active = Some(request);
            let name = ram[0x2210..0x2230].iter().take_while(|&&c| c != 0)
                .map(|&c| if (32..=126).contains(&c) { char::from(c) } else { '?' }).collect();
            let req = Request { session: &self.session, generation: self.generation, request, name };
            if let Ok(bytes) = serde_json::to_vec(&req) {
                let tmp = self.dir.join("request.tmp");
                if std::fs::write(&tmp, bytes).is_ok() { let _ = std::fs::rename(tmp, self.dir.join("request.json")); }
            }
        }
        // A bounded file and a restricted native text alphabet prevent control
        // injection. Publish text completely before status=ready, on this thread.
        let path = self.dir.join("reply.json");
        if std::fs::metadata(&path).map_or(true, |m| m.len() > 4096) { return; }
        let Ok(bytes) = std::fs::read(path) else { return; };
        let Ok(reply) = serde_json::from_slice::<Reply>(&bytes) else { return; };
        if reply.session != self.session || reply.generation != self.generation || reply.request != request
            || !valid_text(&reply.text) { return; }
        ram[TEXT..TEXT+CAPACITY].fill(0);
        ram[TEXT..TEXT+reply.text.len()].copy_from_slice(&reply.text);
        ram[MAILBOX+6..MAILBOX+8].copy_from_slice(&2u16.to_le_bytes());
    }
}
fn valid_text(text: &[u8]) -> bool {
    (2..=CAPACITY).contains(&text.len()) && text.last() == Some(&0)
        && text[..text.len()-1].iter().all(|&c| (32..=126).contains(&c) || [10, 0x81, 0x86, 0x96].contains(&c))
}
#[cfg(test)]
mod tests {
    use super::*;
    fn bridge() -> (Bridge, PathBuf) {
        let unique = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let dir = std::env::temp_dir().join(format!("evermore-test-{unique}"));
        std::fs::create_dir(&dir).unwrap();
        (Bridge { dir: dir.clone(), session: "test-session".into(), generation: 0,
                   active: None, frame: u64::MAX }, dir)
    }
    fn pending_ram() -> Vec<u8> {
        let mut ram = vec![0; 0x20000];
        ram[MAILBOX..MAILBOX+8].copy_from_slice(&[0x47, 0x4d, 1, 0, 7, 0, 1, 0]);
        ram[0x22ec] = 0x20;
        ram[0x2210..0x2215].copy_from_slice(b"Alice");
        ram
    }
    fn reply(dir: &std::path::Path, generation: u64, request: u16) {
        let text = serde_json::json!({"session": "test-session", "generation": generation,
                                     "request": request, "text": [150, 72, 105, 134, 0]});
        std::fs::write(dir.join("reply.json"), text.to_string()).unwrap();
    }
    #[test]
    fn current_name_and_dialogue_only_writes() {
        let (mut bridge, dir) = bridge();
        let mut ram = pending_ram();
        bridge.poll(&mut ram, 0);
        let req: serde_json::Value = serde_json::from_slice(&std::fs::read(dir.join("request.json")).unwrap()).unwrap();
        assert_eq!(req["name"], "Alice");
        assert_eq!(req["request"], 7);
        reply(&dir, 0, 7);
        let before = ram.clone();
        bridge.poll(&mut ram, 6);
        assert_eq!(&ram[TEXT..TEXT+5], &[150, 72, 105, 134, 0]);
        assert_eq!(ram[MAILBOX+6], 2);
        for i in 0..ram.len() {
            if !(TEXT..TEXT+CAPACITY).contains(&i) && !(MAILBOX+6..MAILBOX+8).contains(&i) {
                assert_eq!(ram[i], before[i], "unrelated WRAM changed at {i:x}");
            }
        }
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn reset_wrong_request_and_late_reply_are_rejected() {
        let (mut bridge, dir) = bridge();
        let mut ram = pending_ram();
        bridge.poll(&mut ram, 0);
        reply(&dir, 0, 8);
        bridge.poll(&mut ram, 6);
        assert_eq!(ram[MAILBOX+6], 1);
        bridge.reset();
        reply(&dir, 0, 7);
        bridge.poll(&mut ram, 12);
        assert_eq!(ram[MAILBOX+6], 1);
        reply(&dir, 1, 7);
        ram[MAILBOX+6] = 3; // ROM timeout wins.
        let before = ram.clone();
        bridge.poll(&mut ram, 18);
        assert_eq!(ram, before);
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn bridge_requires_opt_in_and_rom_signature() {
        assert!(Bridge::for_rom(&[]).is_none());
        assert!(Bridge::for_rom(&vec![0; 0x400000]).is_none());
    }
    #[test]
    fn no_requests_or_writes_after_opening() {
        let (mut bridge, dir) = bridge();
        let mut ram = pending_ram();
        ram[0x22ec] = 0;
        reply(&dir, 0, 7);
        let before = ram.clone();
        bridge.poll(&mut ram, 0);
        assert_eq!(ram, before);
        assert!(!dir.join("request.json").exists());
        std::fs::remove_dir_all(dir).unwrap();
    }
    #[test]
    fn bounded_text_only() {
        assert!(valid_text(b"\x96Hi\x86\0"));
        assert!(!valid_text(b"hi\0injected\0"));
        assert!(!valid_text(b"\x8bchoice\0"));
        assert!(!valid_text(&vec![32; 513]));
    }
}
