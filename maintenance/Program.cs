// SPDX-License-Identifier: GPL-3.0-only
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.IO.Pipes;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.ServiceProcess;
using System.Text;
using System.Threading;
using Microsoft.Win32.SafeHandles;

namespace Cadence.Maintenance
{
    internal sealed class MaintenanceService : ServiceBase
    {
        const string ServiceId="CadenceStudio2Maintenance";
        const string PipeId=ServiceId+".v1";
        readonly object gate=new object();
        readonly AutoResetEvent wake=new AutoResetEvent(false);
        MachineStore store; Thread worker,listener; volatile bool stopping,cleanupPending;
        string request="",status="idle",version=""; int progress; NamedPipeServerStream livePipe;

        [DllImport("kernel32.dll",SetLastError=true)] static extern bool GetNamedPipeClientProcessId(SafePipeHandle pipe,out uint pid);
        [DllImport("kernel32.dll",SetLastError=true)] static extern IntPtr OpenProcess(uint access,bool inherit,uint id);
        [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)] static extern bool QueryFullProcessImageName(IntPtr process,uint flags,StringBuilder buffer,ref int length);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
        [DllImport("kernel32.dll",SetLastError=true,CharSet=CharSet.Unicode)]
        static extern uint GetFinalPathNameByHandle(SafeFileHandle file,StringBuilder path,uint length,uint flags);

        internal MaintenanceService() { ServiceName=ServiceId; AutoLog=false; CanShutdown=true; CanStop=true; }
        public static void Main() { ServiceBase.Run(new MaintenanceService()); }
        protected override void OnStart(string[] args) {
            string app=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),"Cadence 2.0");
            string data=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData),"CadenceStudio2","Maintenance");
            store=new MachineStore(app,data,Package.Publisher());
            if(store.State.Phase=="applying") { store.State.Phase="rollback"; store.Save(); }
            Update();
            worker=new Thread(Work){IsBackground=true}; listener=new Thread(Listen){IsBackground=true};
            worker.Start(); listener.Start();
        }
        protected override void OnShutdown() { OnStop(); }
        protected override void OnStop() {
            stopping=true;wake.Set();
            lock(gate) { if(livePipe!=null)livePipe.Dispose(); }
            if(listener!=null)listener.Join(2000);
            if(worker!=null)worker.Join(2000);
        }
        protected override void OnCustomCommand(int command) {
            if(command!=192)return;
            lock(gate) {cleanupPending=true;request="";}
            wake.Set();
        }
        void Update() { lock(gate) { status=store.State.Phase=="confirming"?"trial":store.State.Phase;version=store.State.Version; progress=status=="ready"?100:0; } }
        string Image(uint pid,uint format=0) {
            IntPtr handle=OpenProcess(0x1000,false,pid);
            if(handle==IntPtr.Zero)return null;
            try {
                var buffer=new StringBuilder(32768); int length=buffer.Capacity;
                return QueryFullProcessImageName(handle,format,buffer,ref length)?buffer.ToString():null;
            } finally {CloseHandle(handle);}
        }
        string InstalledImage() {
            using(var file=new FileStream(store.Exe,FileMode.Open,FileAccess.Read,FileShare.ReadWrite|FileShare.Delete)) {
                var path=new StringBuilder(32768);
                uint length=GetFinalPathNameByHandle(file.SafeFileHandle,path,(uint)path.Capacity,2);
                if(length==0 || length>=path.Capacity)throw new IOException("Application image identity unavailable");
                return path.ToString();
            }
        }
        bool InUse(uint except=0) {
            try {
                string installed=null;
                foreach (var p in Process.GetProcessesByName("Cadence")) using(p) {
                    uint id=(uint)p.Id;
                    if(id==except)continue;
                    string image=Image(id,1);
                    if(image==null) {try{if(p.HasExited)continue;}catch(InvalidOperationException){continue;} return true;}
                    if(installed==null)installed=InstalledImage();
                    if(String.Equals(image,installed,StringComparison.OrdinalIgnoreCase))return true;
                }
                return false;
            } catch(IOException) {return true;}
              catch(UnauthorizedAccessException) {return true;}
              catch(System.ComponentModel.Win32Exception) {return true;}
              catch(InvalidOperationException) {return true;}
        }
        void Report(string s,int pct) { lock(gate) {status=s;progress=pct;} }
        void Check(bool previews) {
            Report("checking",0);
            Package p;
#if CADENCE_TEST_SERVICE
            string fixture=Path.Combine(store.Private,"fixture");
            string json=Path.Combine(fixture,"update.json");
            var data=(Dictionary<string,object>)ReleaseSource.Json.DeserializeObject(File.ReadAllText(json));
            p=new Package{Version=(string)data["version"],Size=Convert.ToInt64(data["size"]),Preview=(bool)data["preview"],Digest=(string)data["sha256"],Signature=(string)data["signature"]};
            p.Verify(store.Key);
            if((!previews && p.Preview) || Package.Number(p.Version)<=Package.Number(store.Installed())) {Update();return;}
#else
            var source=new ReleaseSource();
            p=source.Discover(store.Installed(),previews,store.Key);
            if(p==null){Update();return;}
#endif
            if(p.Version==store.State.Failed){Update();return;}
            store.RemoveDownload();
            lock(gate)version=p.Version;
            Report("downloading",0);
#if CADENCE_TEST_SERVICE
            File.Copy(Path.Combine(fixture,"update.zip"),store.Zip);
#else
            source.Download(p,store.Zip,v=>Report("downloading",v),()=>stopping || cleanupPending);
#endif
            store.Stage(p);Update();
        }
        void Work() {
            DateTime collectAfter=DateTime.MinValue;
            while(!stopping) {
                string job;
                lock(gate){job=request;request="";}
                try {
                    if(cleanupPending) {
                        if(!InUse()) {
                            if(store.State.Phase=="confirming")store.Confirm();
                            store.RemoveManaged();Update();
                            ThreadPool.QueueUserWorkItem(_=>Stop());
                            return;
                        }
                    } else {
                        if(job=="CHECK_STABLE" || job=="CHECK_PREVIEW") Check(job=="CHECK_PREVIEW");
                        else if(job=="READY") {store.Confirm();Update();}
                        else if(job=="APPLY"){store.State.Phase="waiting";store.Save();Update();}
                        if(store.State.Phase=="waiting" && !InUse()) {
                            Report("applying",0);store.Apply();Update();
                        }
                        if(store.State.Phase=="trial" && DateTime.UtcNow.Ticks>=store.State.Deadline) {
                            store.State.Phase="rollback";store.Save();Update();
                        }
                        if(store.State.Phase=="rollback" && !InUse()){store.Restore();Update();}
                        if(store.State.Phase=="confirming"){store.Confirm();Update();}
                        if(store.State.Phase=="installed" && DateTime.UtcNow>=collectAfter) {
                            collectAfter=DateTime.UtcNow.AddHours(1);
                            store.Collect();
                        }
                    }
                } catch(Exception e) {
                    if(store.State.Phase=="applying") {store.State.Phase="rollback";store.Save();Update();}
                    else if(store.State.Phase=="rollback" || store.State.Phase=="confirming" || cleanupPending ||
                            (store.State.Phase=="installed" && job!="CHECK_STABLE" && job!="CHECK_PREVIEW"))Update();
                    else {
                        store.State.Phase="failed";store.Save();Update();
                    }
                    try {store.RecordFailure(e);}catch(Exception){}
                }
                wake.WaitOne(500);
            }
        }
        string Command(string verb,uint pid) {
            bool blocked=false;
            lock(gate) {
                if(!cleanupPending && request=="" && !stopping) {
                    if((verb=="CHECK_STABLE" || verb=="CHECK_PREVIEW") && (status=="idle" || status=="installed" || status=="failed")) {
                        request=verb;status="checking";progress=0;wake.Set();
                    } else if(verb=="APPLY" && status=="ready") {
                        blocked=InUse(pid);
                        if(!blocked){request=verb;status="waiting";wake.Set();}
                    } else if(verb=="READY" && status=="trial" && String.Equals(Image(pid),store.Exe,StringComparison.OrdinalIgnoreCase)) {
                        request=verb;wake.Set();
                    }
                }
                return ReleaseSource.Json.Serialize(new {state=status,version=version,progress=progress,blocked=blocked})+"\n";
            }
        }
        static string Receive(NamedPipeServerStream pipe) {
            var bytes=new byte[32];int length=0;var until=DateTime.UtcNow.AddMilliseconds(900);
            while(length<bytes.Length) {
                var task=pipe.BeginRead(bytes,length,bytes.Length-length,null,null);
                try {
                    int wait=(int)Math.Max(0,(until-DateTime.UtcNow).TotalMilliseconds);
                    if(!task.AsyncWaitHandle.WaitOne(wait)) {pipe.Dispose();task.AsyncWaitHandle.WaitOne(1000);return null;}
                    int n=pipe.EndRead(task);if(n==0)return null;length+=n;
                } finally {task.AsyncWaitHandle.Close();}
                if(bytes[length-1]==10) {
                    for(int i=0;i<length-1;i++)if(bytes[i]!=95 && (bytes[i]<65 || bytes[i]>90))return null;
                    return Encoding.ASCII.GetString(bytes,0,length-1);
                }
            }
            return null;
        }
        void Listen() {
            var acl=new PipeSecurity();
            var service=(SecurityIdentifier)new NTAccount("NT SERVICE",ServiceId).Translate(typeof(SecurityIdentifier));
            acl.AddAccessRule(new PipeAccessRule(new SecurityIdentifier("S-1-5-2"),PipeAccessRights.FullControl,AccessControlType.Deny));
            acl.AddAccessRule(new PipeAccessRule(service,PipeAccessRights.FullControl,AccessControlType.Allow));
            acl.AddAccessRule(new PipeAccessRule(new SecurityIdentifier("S-1-5-18"),PipeAccessRights.FullControl,AccessControlType.Allow));
            acl.AddAccessRule(new PipeAccessRule(new SecurityIdentifier("S-1-3-4"),PipeAccessRights.ReadPermissions,AccessControlType.Allow));
            acl.AddAccessRule(new PipeAccessRule(new SecurityIdentifier("S-1-5-4"),
                PipeAccessRights.ReadData|PipeAccessRights.WriteData|PipeAccessRights.Synchronize,AccessControlType.Allow));
            while(!stopping) {
                try {
                    using(var pipe=new NamedPipeServerStream(PipeId,PipeDirection.InOut,1,PipeTransmissionMode.Byte,
                               PipeOptions.Asynchronous,512,512,acl)) {
                        lock(gate)livePipe=pipe;
                        pipe.WaitForConnection();if(!pipe.IsConnected)continue;
                        uint pid;if(!GetNamedPipeClientProcessId(pipe.SafePipeHandle,out pid))continue;
                        string verb=Receive(pipe);
                        if(verb==null || !(new[]{"STATUS","CHECK_STABLE","CHECK_PREVIEW","APPLY","READY"}).Contains(verb))continue;
                        byte[] result=Encoding.ASCII.GetBytes(Command(verb,pid));pipe.Write(result,0,result.Length);
                    }
                } catch(IOException) {if(!stopping)Thread.Sleep(50);}
                  catch(UnauthorizedAccessException){if(!stopping)Thread.Sleep(300);}
                  catch(ObjectDisposedException){if(!stopping)Thread.Sleep(50);}
                finally{lock(gate)livePipe=null;}
            }
        }
    }
}
