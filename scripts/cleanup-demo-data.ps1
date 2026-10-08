. (Join-Path $PSScriptRoot 'common.ps1')
Import-LocalEnvironment
if ($env:DB_URL -notmatch '^jdbc:mysql://127\.0\.0\.1:3306/elder_care_dev(?:\?|$)') { throw '只允许清理独立开发库 elder_care_dev' }
$mysql='C:/Program Files/MySQL/MySQL Server 8.0/bin/mysql.exe'
$env:MYSQL_PWD=$env:DB_PASSWORD
try {
  $storageRoot=[IO.Path]::GetFullPath((Join-Path $ProjectRoot 'backend/uploads'))
  $mediaRows=@(& $mysql --host=127.0.0.1 --port=3306 "--user=$env:DB_USERNAME" --batch --skip-column-names elder_care_dev "--execute=SELECT image_path FROM event WHERE description LIKE 'DEMO %' AND image_path IS NOT NULL UNION ALL SELECT v.file_path FROM event_video v JOIN event e ON e.id=v.event_id WHERE e.description LIKE 'DEMO %' AND v.file_path IS NOT NULL UNION ALL SELECT face_path FROM person WHERE person_code LIKE 'DEMO-%' AND face_path IS NOT NULL;")
  $sql="START TRANSACTION; DELETE FROM notification_job WHERE event_id IN (SELECT id FROM event WHERE description LIKE 'DEMO %'); DELETE FROM event_handle_record WHERE event_id IN (SELECT id FROM event WHERE description LIKE 'DEMO %'); DELETE FROM event_video WHERE event_id IN (SELECT id FROM event WHERE description LIKE 'DEMO %'); DELETE FROM emotion_sample WHERE person_code LIKE 'DEMO-%'; DELETE FROM track_point WHERE person_code LIKE 'DEMO-%' OR track_id LIKE 'DEMO-%'; DELETE FROM interaction_record WHERE elder_code LIKE 'DEMO-%' OR worker_code LIKE 'DEMO-%' OR record_no LIKE 'DEMO-%'; DELETE FROM family_binding WHERE person_code LIKE 'DEMO-%'; DELETE FROM sys_user WHERE username='family01'; DELETE FROM event WHERE description LIKE 'DEMO %'; DELETE FROM danger_zone WHERE zone_code LIKE 'DEMO-%'; DELETE FROM person WHERE person_code LIKE 'DEMO-%'; COMMIT;"
  & $mysql --host=127.0.0.1 --port=3306 "--user=$env:DB_USERNAME" elder_care_dev "--execute=$sql"
  if($LASTEXITCODE -ne 0){throw 'DEMO数据清理失败'}
  $deletedFiles=0
  foreach($name in $mediaRows){
    if([string]::IsNullOrWhiteSpace($name)){continue}
    $candidate=if([IO.Path]::IsPathRooted($name)){[IO.Path]::GetFullPath($name)}else{[IO.Path]::GetFullPath((Join-Path $storageRoot $name))}
    if(-not $candidate.StartsWith($storageRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw "拒绝删除存储目录外文件：$candidate"}
    if(Test-Path -LiteralPath $candidate -PathType Leaf){Remove-Item -LiteralPath $candidate -Force;$deletedFiles++}
  }
  $preview=[IO.Path]::GetFullPath((Join-Path $ProjectRoot 'runtime/demo-preview.mp4'))
  if($preview.StartsWith([IO.Path]::GetFullPath((Join-Path $ProjectRoot 'runtime'))+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $preview -PathType Leaf)){Remove-Item -LiteralPath $preview -Force;$deletedFiles++}
  Write-Host "已清理DEMO演示记录和 $deletedFiles 个对应媒体文件；正式数据未修改。"
} finally { Remove-Item Env:MYSQL_PWD -ErrorAction SilentlyContinue }
