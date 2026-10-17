// Read actual TOTK shader containers using the pinned third-party ShaderLibrary.
using ShaderLibrary;
using System.Security.Cryptography;
using System.Text.Json;
if(args.Length!=2)throw new ArgumentException("usage: shader_inventory decoded-assets-dir output-dir");
Directory.CreateDirectory(args[1]);var rows=new List<object>();var failed=new List<object>();var keys=new HashSet<string>();
void Export(BnshFile bnsh,string source,string model) {
 for(int i=0;i<bnsh.Variations.Count;i++) {
  var p=bnsh.Variations[i].BinaryProgram;
  var stages=new (string, BnshFile.ShaderCode?)[]{("vs",p.VertexShader),("ps",p.FragmentShader),("cs",p.ComputeShader),("gs",p.GeometryShader),("hs",p.TessellationControlShader),("ds",p.TessellationEvalShader)};
  foreach(var (stage,code) in stages)if(code!=null) {
   var hash=Convert.ToHexString(SHA256.HashData(code.ControlCode)).ToLowerInvariant();
   var joined=new byte[code.ControlCode.Length+code.ByteCode.Length];code.ControlCode.CopyTo(joined,0);code.ByteCode.CopyTo(joined,code.ControlCode.Length);
   string key=Convert.ToHexString(SHA256.HashData(joined)).ToLowerInvariant();
   if(keys.Add(key)){File.WriteAllBytes(Path.Combine(args[1],key+".code"),code.ByteCode);File.WriteAllBytes(Path.Combine(args[1],key+".control"),code.ControlCode);}
   rows.Add(new {source,model,variation=i,stage,key,control_key=hash[..16],control_sha256=hash,control_size=code.ControlCode.Length,code_size=code.ByteCode.Length,code_sha256=Convert.ToHexString(SHA256.HashData(code.ByteCode)).ToLowerInvariant()});
  }
 }
}
foreach(var file in Directory.EnumerateFiles(args[0],"*",SearchOption.AllDirectories).Where(p=>p.EndsWith(".bfsha")||p.EndsWith(".bnsh")).Order()) {
 try {
  using var stream=File.OpenRead(file);
  if(file.EndsWith(".bnsh"))Export(new BnshFile(stream),Path.GetFileName(file),"SDK");
  else {var archive=new BfshaFile(stream);foreach(var model in archive.ShaderModels.Values)Export(model.BnshFile,Path.GetFileName(file),model.Name);}
  Console.WriteLine(JsonSerializer.Serialize(new {file,records=rows.Count,unique=keys.Count}));
 }catch(Exception e){failed.Add(new {file,error=e.ToString()});Console.Error.WriteLine(e.Message);}
}
File.WriteAllText(Path.Combine(args[1],"inventory.json"),JsonSerializer.Serialize(new {status=failed.Count==0?"pass":"partial",rows,failed,unique=keys.Count},new JsonSerializerOptions{WriteIndented=true}));
return failed.Count==0?0:1;
