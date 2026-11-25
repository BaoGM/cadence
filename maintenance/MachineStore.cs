// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.ComponentModel;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.RegularExpressions;

namespace Cadence.Maintenance
{
    internal sealed class Record {
        public string Phase = "idle", Version = "", Previous = "", Digest = "", Signature = "";
        public bool Preview;
        public long Size, Deadline;
        public string Failed = "";
    }

    internal sealed class Change {
        public string Name, Before, After;
    }

    internal sealed class MachineStore
    {
        internal readonly string Root, Private;
        internal readonly RSAParameters Key;
        internal Record State;
        internal string Exe { get { return Path.Combine(Root,"Cadence.exe"); } }
        internal string Zip { get { return Path.Combine(Private,"download.zip"); } }
        string Files { get { return Path.Combine(Private,"staged"); } }
        string Backups { get { return Path.Combine(Private,"backup"); } }
        static readonly StringComparer Names=StringComparer.OrdinalIgnoreCase;
        readonly bool guarded;
        SecurityIdentifier serviceSid;
        readonly HashSet<string> writers;

#if CADENCE_STORE_TEST
        internal MachineStore(string root,string state,RSAParameters key,bool protectedFolders)
#else
        internal MachineStore(string root,string state,RSAParameters key)
#endif
        {
            Root=Path.GetFullPath(root); Private=Path.GetFullPath(state); Key=key;
#if CADENCE_STORE_TEST
            guarded=protectedFolders;
#else
            guarded=true;
#endif
            writers=new HashSet<string> { "S-1-5-18","S-1-5-32-544","S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464" };
            if (guarded) {
                serviceSid=(SecurityIdentifier)new NTAccount("NT SERVICE","CadenceStudio2Maintenance").Translate(typeof(SecurityIdentifier));
                writers.Add(serviceSid.Value);
                Guard(Root); Guard(Path.GetDirectoryName(Private)); Guard(Private);
            }
            State=Load<Record>("state.json") ?? new Record();
        }

        void Guard(string path)
        {
            FileAttributes attrs=File.GetAttributes(path);
            if ((attrs & FileAttributes.ReparsePoint)!=0) throw new InvalidDataException("Unexpected filesystem link");
            if (!guarded) return;
            FileSystemSecurity acl=(attrs & FileAttributes.Directory)!=0 ? (FileSystemSecurity)Directory.GetAccessControl(path) : File.GetAccessControl(path);
            const FileSystemRights write=FileSystemRights.Write|FileSystemRights.Delete|
                FileSystemRights.DeleteSubdirectoriesAndFiles|FileSystemRights.ChangePermissions|FileSystemRights.TakeOwnership;
            bool ownerRestricted=false;
            foreach (FileSystemAccessRule rule in acl.GetAccessRules(true,true,typeof(SecurityIdentifier))) {
                if (rule.IdentityReference.Value=="S-1-3-4" && (rule.PropagationFlags&PropagationFlags.InheritOnly)==0) ownerRestricted=true;
                if (rule.AccessControlType==AccessControlType.Allow && (rule.PropagationFlags & PropagationFlags.InheritOnly)==0 &&
                    (rule.FileSystemRights & write)!=0 && !writers.Contains(rule.IdentityReference.Value))
                    throw new InvalidDataException("A machine update location is writable by another principal");
            }
            string owner=acl.GetOwner(typeof(SecurityIdentifier)).Value;
            if (!writers.Contains(owner) && !(owner=="S-1-5-19" && ownerRestricted)) throw new InvalidDataException("Unexpected update location owner");
        }
        FileSystemSecurity PublicAcl(bool directory) {
            FileSystemSecurity acl=directory ? (FileSystemSecurity)new DirectorySecurity() : new FileSecurity();
            acl.SetAccessRuleProtection(true,false);
            var inheritance=directory ? InheritanceFlags.ContainerInherit|InheritanceFlags.ObjectInherit : InheritanceFlags.None;
            foreach (var item in new Dictionary<string,FileSystemRights> {
                {"S-1-5-18",FileSystemRights.FullControl},{"S-1-5-32-544",FileSystemRights.FullControl},
                {"S-1-5-32-545",FileSystemRights.ReadAndExecute},{serviceSid.Value,FileSystemRights.Modify},
                {"S-1-3-4",FileSystemRights.ReadPermissions} })
                acl.AddAccessRule(new FileSystemAccessRule(new SecurityIdentifier(item.Key),item.Value,inheritance,PropagationFlags.None,AccessControlType.Allow));
            return acl;
        }
        static bool Exists(string path) {
            try { File.GetAttributes(path); return true; }
            catch (FileNotFoundException) { return false; }
            catch (DirectoryNotFoundException) { return false; }
        }
        static void Name(string path)
        {
            if (String.IsNullOrEmpty(path) || path.Length>700) throw new InvalidDataException("Invalid package member");
            foreach (string part in path.Split('/')) {
                if (part.Length==0 || part.Length>200 || part.EndsWith(".") || part.EndsWith(" ") ||
                    part.IndexOfAny(Path.GetInvalidFileNameChars())>=0 ||
                    Regex.IsMatch(part,@"\A(?:CON|PRN|AUX|NUL|CLOCK\$|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\.|\z)",RegexOptions.IgnoreCase))
                    throw new InvalidDataException("Invalid package member");
            }
        }
        string Destination(string baseDir,string relative,bool createParents)
        {
            Name(relative); Guard(baseDir); string path=baseDir; var components=relative.Split('/');
            for (int i=0;i<components.Length;i++) {
                path=Path.Combine(path,components[i]);
                if (Exists(path)) Guard(path);
                else if (createParents && i+1<components.Length) {
                    if (guarded && baseDir==Root) Directory.CreateDirectory(path,(DirectorySecurity)PublicAcl(true));
                    else Directory.CreateDirectory(path);
                    Guard(path);
                }
            }
            return path;
        }
        static string Hash(Stream stream) {
            using (var hash=SHA256.Create()) return BitConverter.ToString(hash.ComputeHash(stream)).Replace("-","").ToLowerInvariant();
        }
        static string Hash(string path) { using (var input=File.OpenRead(path)) return Hash(input); }
        static string CurrentHash(string path) { return File.Exists(path) ? Hash(path) : ""; }
        internal string Installed() {
            Guard(Exe);
            var ver=FileVersionInfo.GetVersionInfo(Exe);
            string value=String.Format(System.Globalization.CultureInfo.InvariantCulture,"{0}.{1}.{2}",ver.FileMajorPart,ver.FileMinorPart,ver.FileBuildPart);
            Package.Number(value); return value;
        }
        internal void Save() { Store("state.json",State); }
        internal void RecordFailure(Exception error) {
            string message=error.Message;
            Store("last-error.json",new {utc=DateTime.UtcNow.ToString("o"),state=State.Phase,
                type=error.GetType().Name,message=message.Substring(0,Math.Min(400,message.Length))});
        }
        T Load<T>(string name) where T:class {
            string path=Destination(Private,name,false);
            if (!File.Exists(path)) return null;
            var info=new FileInfo(path);
            if (info.Length>16*1024*1024) throw new InvalidDataException("Maintenance state size");
            return new System.Web.Script.Serialization.JavaScriptSerializer {MaxJsonLength=16*1024*1024}.Deserialize<T>(File.ReadAllText(path));
        }
        void Store(string name,object data) {
            string dest=Destination(Private,name,false),temp=dest+".tmp";
            if (Exists(temp)) { Guard(temp); File.Delete(temp); }
            var json=new System.Web.Script.Serialization.JavaScriptSerializer {MaxJsonLength=16*1024*1024};
            byte[] bytes=Encoding.UTF8.GetBytes(json.Serialize(data));
            using (var f=new FileStream(temp,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { f.Write(bytes,0,bytes.Length); f.Flush(true); }
            Promote(temp,dest);
        }
        void EmptyPrivate(string path) {
            if (Directory.Exists(path)) {
                Guard(path);
                foreach (string entry in Directory.EnumerateFileSystemEntries(path)) {
                    Guard(entry);
                    if (Directory.Exists(entry)) EmptyPrivate(entry); else File.Delete(entry);
                }
                Directory.Delete(path);
            }
        }
        void Fresh(string directory) { EmptyPrivate(directory); Directory.CreateDirectory(directory); Guard(directory); }
        internal void RemoveDownload() { if (Exists(Zip)) {Guard(Zip); File.Delete(Zip);} }
        [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)]
        static extern bool MoveFileEx(string existing,string target,uint flags);
        static void Promote(string existing,string target) {
            if(!MoveFileEx(existing,target,1|8)) throw new Win32Exception(Marshal.GetLastWin32Error());
        }
        void ReplaceFrom(string source,string target) {
            string tmp=Path.Combine(Path.GetDirectoryName(target),".cadence-"+Guid.NewGuid().ToString("N")+".tmp");
            try {
                using (var input=File.OpenRead(source))
                using (var output=guarded ? new FileStream(tmp,FileMode.CreateNew,FileSystemRights.Write,FileShare.None,65536,FileOptions.None,(FileSecurity)PublicAcl(false)) :
                    new FileStream(tmp,FileMode.CreateNew,FileAccess.Write,FileShare.None)) { input.CopyTo(output); output.Flush(true); }
                Guard(tmp);
                Promote(tmp,target);
            } finally { if (File.Exists(tmp)) File.Delete(tmp); }
        }
        internal void Stage(Package p) {
            p.Verify(Key);
            if (Package.Number(p.Version)<=Package.Number(Installed()) || p.Version==State.Failed) throw new InvalidDataException("Wrong update version");
            Fresh(Files); bool hasExe=false, hasRuntime=false; long total=0; int count=0;
            var items=new Dictionary<string,string>(Names);
            using (var file=new FileStream(Zip,FileMode.Open,FileAccess.Read,FileShare.Read)) {
                if (file.Length!=p.Size || Hash(file)!=p.Digest) throw new InvalidDataException("Invalid package digest");
                file.Position=0;
                using (var archive=new ZipArchive(file,ZipArchiveMode.Read,true)) {
                    if (archive.Entries.Count>25000) throw new InvalidDataException("Package entry count");
                    foreach (var entry in archive.Entries) {
                        string name=entry.FullName;
                        if (name=="Cadence/") continue;
                        if (!name.StartsWith("Cadence/",StringComparison.Ordinal) || name.Contains("\\") ||
                            ((entry.ExternalAttributes>>16)&0xf000)==0xa000 || (entry.ExternalAttributes&0x400)!=0)
                            throw new InvalidDataException("Unexpected package entry");
                        name=name.Substring(8);
                        bool dir=name.EndsWith("/",StringComparison.Ordinal);
                        if (dir) name=name.Substring(0,name.Length-1);
                        Name(name);
                        string first=name.Split('/')[0], runtime="_internal-"+p.Version;
                        if (name=="_internal" && dir) continue;
                        if (name=="_internal/layout.txt" && !dir) {
                            if(entry.Length>40)throw new InvalidDataException("Unexpected compatibility marker");
                            using(var input=entry.Open()) {
                                byte[] content=new byte[41]; int n=0,got;
                                while(n<content.Length && (got=input.Read(content,n,content.Length-n))>0)n+=got;
                                string marker=Encoding.ASCII.GetString(content,0,n);
                                if(marker!=runtime+"\n" && marker!=runtime+"\r\n")throw new InvalidDataException("Inconsistent compatibility marker");
                            }
                            continue;
                        }
                        if (first=="Associer Cadence.cmd" && name==first && !dir) continue;
                        if (first!="Licences" && first!=runtime && !(name=="Cadence.exe" && !dir))
                            throw new InvalidDataException("Unexpected product path");
                        string target=Destination(Files,name,true);
                        if (dir) { Directory.CreateDirectory(target); continue; }
                        total=checked(total+entry.Length);
                        if (total>4L*1024*1024*1024 || ++count>25000) throw new InvalidDataException("Uncompressed package size");
                        using (var input=entry.Open())
                        using (var output=new FileStream(target,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                            byte[] bytes=new byte[65536]; int n; long copied=0;
                            while ((n=input.Read(bytes,0,bytes.Length))>0) {
                                copied+=n; if (copied>entry.Length) throw new InvalidDataException("Bad compressed entry");
                                output.Write(bytes,0,n);
                            }
                            if (copied!=entry.Length) throw new EndOfStreamException();
                        }
                        items.Add(name,Hash(target));
                        hasExe |= name=="Cadence.exe"; hasRuntime |= first==runtime;
                    }
                }
            }
            var ver=hasExe ? FileVersionInfo.GetVersionInfo(Path.Combine(Files,"Cadence.exe")) : null;
            if (!hasRuntime || ver==null || new Version(ver.FileMajorPart,ver.FileMinorPart,ver.FileBuildPart)!=Package.Number(p.Version))
                throw new InvalidDataException("Incomplete or inconsistent runtime");
            Store("staged-files.json",items);
            State.Version=p.Version; State.Previous=Installed(); State.Phase="ready"; State.Size=p.Size;
            State.Digest=p.Digest; State.Signature=p.Signature; State.Preview=p.Preview; Save();
        }
        Dictionary<string,string> Receipt() { return Load<Dictionary<string,string>>("receipt.json") ?? new Dictionary<string,string>(Names); }
        Dictionary<string,string> PriorFiles() {
            var old=Receipt();
            string path=Destination(Root,"uninstall/installed-files.txt",false);
            if (!File.Exists(path)) return old;
            if(new FileInfo(path).Length>16*1024*1024) throw new InvalidDataException("Installer receipt size");
            foreach (string line in File.ReadLines(path)) {
                int bar=line.IndexOf('|');
                if (bar!=64 || !Regex.IsMatch(line.Substring(0,bar),@"\A[0-9a-fA-F]{64}\z")) continue;
                string name=line.Substring(bar+1).Replace('\\','/');
                if(!old.ContainsKey(name)) old[name]=line.Substring(0,bar).ToLowerInvariant();
            }
            return old;
        }
        internal void Apply() {
            if(Installed()!=State.Previous) throw new InvalidDataException("Installed version changed");
            var desc=new Package {Version=State.Version,Size=State.Size,Preview=State.Preview,Digest=State.Digest,Signature=State.Signature};
            desc.Verify(Key);
            if (Hash(Zip)!=desc.Digest) throw new InvalidDataException("Changed protected archive");
            var files=Load<Dictionary<string,string>>("staged-files.json");
            var old=PriorFiles(); var plan=new List<Change>(); Fresh(Backups);
            foreach (var item in files.OrderBy(i=>i.Key=="Cadence.exe" ? 1 : 0)) {
                string target=Destination(Root,item.Key,false); string prior=CurrentHash(target);
                if (Hash(Destination(Files,item.Key,false))!=item.Value) throw new InvalidDataException("Changed staging file");
                if (prior==item.Value) continue;
                if(prior!="" && item.Key!="Cadence.exe") {
                    string recorded;
                    if (!old.TryGetValue(item.Key,out recorded) || prior!=recorded) throw new InvalidDataException("Local file conflict");
                }
                if (prior!="") {
                    using(var input=File.OpenRead(target))
                    using(var output=new FileStream(Destination(Backups,item.Key,true),FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                        input.CopyTo(output);output.Flush(true);
                    }
                }
                plan.Add(new Change{Name=item.Key,Before=prior,After=item.Value});
            }
            Store("transaction.json",plan); State.Phase="applying"; Save();
            foreach (var item in plan) {
                string target=Destination(Root,item.Name,true);
                if (CurrentHash(target)!=item.Before) throw new IOException("Update conflict");
                ReplaceFrom(Destination(Files,item.Name,false),target);
            }
            State.Phase="trial"; State.Deadline=DateTime.UtcNow.AddMinutes(3).Ticks; Save();
        }
        internal void Confirm() {
            if (State.Phase!="trial" && State.Phase!="confirming") return;
            if (Installed()!=State.Version) throw new InvalidDataException("Installed version changed");
            if (State.Phase=="trial") { State.Phase="confirming"; Save(); }
            var receipt=Load<Dictionary<string,string>>("staged-files.json");
            var obsolete=Load<Dictionary<string,string>>("retired.json") ?? new Dictionary<string,string>(Names);
            foreach(var item in PriorFiles()) {
                if(!receipt.ContainsKey(item.Key) && Retirable(item.Key,State.Version)) obsolete[item.Key]=item.Value;
            }
            Store("retired.json",obsolete);
            Store("receipt.json",receipt);
            State.Phase="installed"; State.Failed=""; Save();
            Collect();
        }
        static bool Retirable(string name,string active) {
            string first=name.Split('/')[0];
            if(Names.Equals(first,"_internal-"+active) || first==name)return false;
            return Names.Equals(first,"Licences") || Names.Equals(first,"_internal") ||
                Regex.IsMatch(first,@"\A_internal-2\.[0-9]{1,4}\.[0-9]{1,4}\z",RegexOptions.IgnoreCase);
        }
        void RemoveRecorded(string name,string digest) {
            string target=Destination(Root,name,false);
            if (!File.Exists(target) || Hash(target)!=digest) return;
            File.Delete(target);
            string parent=Path.GetDirectoryName(target);
            while (!Names.Equals(parent,Root) && Directory.Exists(parent) && !Directory.EnumerateFileSystemEntries(parent).Any()) {
                Guard(parent); Directory.Delete(parent); parent=Path.GetDirectoryName(parent);
            }
        }
        internal void Collect() {
            if(State.Phase=="installed" || State.Phase=="failed") {
                EmptyPrivate(Files); EmptyPrivate(Backups); RemoveDownload();
            }
            var obsolete=Load<Dictionary<string,string>>("retired.json");
            if(obsolete==null || obsolete.Count==0)return;
            string active=Installed(); int before=obsolete.Count;
            foreach(var item in obsolete.ToArray()) {
                try {
                    if(Retirable(item.Key,active))RemoveRecorded(item.Key,item.Value);
                    obsolete.Remove(item.Key);
                } catch(IOException) { } catch(UnauthorizedAccessException) { }
            }
            if(before!=obsolete.Count)Store("retired.json",obsolete);
        }
        internal void Restore() {
            var plan=Load<List<Change>>("transaction.json");
            if(plan==null) throw new InvalidDataException("Missing maintenance transaction");
            foreach (var item in plan.AsEnumerable().Reverse()) {
                string target=Destination(Root,item.Name,false); string current=CurrentHash(target);
                if (current==item.Before) continue;
                if (current!=item.After) throw new IOException("Modified file during recovery");
                if (item.Before=="") RemoveRecorded(item.Name,item.After);
                else {
                    string backup=Destination(Backups,item.Name,false);
                    if (Hash(backup)!=item.Before) throw new InvalidDataException("Rollback backup changed");
                    ReplaceFrom(backup,target);
                }
            }
            State.Failed=State.Version; State.Phase="failed"; Save();
            EmptyPrivate(Files); EmptyPrivate(Backups); RemoveDownload();
        }
        internal void RemoveManaged() {
            if (State.Phase=="applying" || State.Phase=="rollback" || State.Phase=="trial") Restore();
            Collect();
            var pending=Load<Dictionary<string,string>>("retired.json");
            if(pending!=null && pending.Count!=0)throw new IOException("Previous runtime is still in use");
            foreach (var item in Receipt().OrderByDescending(i=>i.Key.Length)) {
                if (item.Key=="Cadence.exe") continue;
                RemoveRecorded(item.Key,item.Value);
            }
            State=new Record(); Save(); Store("receipt.json",new Dictionary<string,string>());
        }
    }
}
