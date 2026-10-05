#!/usr/bin/env python3
"""Manual, bounded local member export. No joining or gateway scraping.

CLI requires an expected account ID, explicit output and row/byte/deadline
limits. JSON preserves raw text; CSV applies a text guard, not a certification
that every spreadsheet reader treats its cells as text.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime,timezone
import io
import json
import os
from pathlib import Path
import sys
import time

BASE_DIR=Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:sys.path.insert(0,str(BASE_DIR))

FIELDS=('id','username','global_name','display_name','discriminator','bot','system','joined_at','roles','avatar_url')
MAX_ROWS=100000
MAX_BYTES=16*1024*1024


@dataclass(frozen=True)
class ExportResult:
    source: str
    scope: str
    coverage: str
    rows: list[dict]
    truncation_reason: str | None


def member_row(member):
    return {'id':member.id,'username':member.name,'global_name':getattr(member,'global_name',None),
        'display_name':member.display_name,'discriminator':getattr(member,'discriminator',None),
        'bot':member.bot,'system':member.system,'joined_at':member.joined_at.isoformat() if member.joined_at else None,
        'roles':','.join(r.name for r in member.roles if r.name!='@everyone'),'avatar_url':str(member.display_avatar.url)}


def rest_row(guild,data):
    user=data['user'];identifier=int(user['id'])
    if identifier<=0 or not isinstance(user['username'],str):raise ValueError('invalid_member_identity')
    names=','.join(r.name for r in guild.roles if str(r.id) in {str(v) for v in data.get('roles',[])} and r.name!='@everyone')
    avatar=user.get('avatar')
    return {'id':identifier,'username':user['username'],'global_name':user.get('global_name'),
        'display_name':data.get('nick') or user.get('global_name') or user['username'],
        'discriminator':user.get('discriminator'),'bot':user.get('bot',False),'system':user.get('system',False),
        'joined_at':data.get('joined_at'),'roles':names,
        'avatar_url':f"https://cdn.discordapp.com/avatars/{identifier}/{avatar}.png" if avatar else None}


def _limits(max_rows,max_bytes):
    if type(max_rows) is not int or not 1<=max_rows<=MAX_ROWS or type(max_bytes) is not int or not 1024<=max_bytes<=MAX_BYTES:
        raise ValueError('invalid_export_limits')


def verify_identity(client,expected_id):
    if not str(expected_id).isdecimal() or int(expected_id)<=0 or str(getattr(getattr(client,'user',None),'id',''))!=str(expected_id):
        raise ValueError('account_identity_mismatch')


async def resolve_guild(client,args):
    # Cached membership only: no invite acceptance, fetch, or new join capability.
    if args.guild_id:
        guild=client.get_guild(args.guild_id)
        if guild is None:raise ValueError('guild_not_available')
        return guild
    found=[g for g in client.guilds if g.name==args.guild_name]
    if len(found)!=1:raise ValueError('guild_name_missing_or_ambiguous_use_id')
    return found[0]


async def fetch_all_members(client,guild,*,max_rows,max_bytes,deadline,page_size=1000,allow_cached_fallback=False):
    _limits(max_rows,max_bytes)
    if type(page_size) is not int or not 1<=page_size<=1000:raise ValueError('invalid_page_size')
    if not isinstance(deadline,(int,float)) or not time.monotonic()<deadline<=time.monotonic()+300:
        raise ValueError('bounded_deadline_required')
    from discord.http import Route
    rows=[];seen=set();after=0;used=0;reason=None
    try:
        while True:
            remaining=deadline-time.monotonic()
            if remaining<=0:reason='deadline';break
            async with asyncio.timeout(remaining):
                page=await client.http.request(Route('GET','/guilds/{guild_id}/members',guild_id=guild.id),
                    params={'limit':min(page_size,max_rows-len(rows)+1),'after':after})
            if not isinstance(page,list) or len(page)>page_size:reason='invalid_page';break
            if not page:break
            ids=[int(value['user']['id']) for value in page]
            if any(identifier<=after for identifier in ids) or ids!=sorted(set(ids)):
                reason='cursor_not_advancing';break
            for value in page:
                row=rest_row(guild,value)
                size=len(json.dumps(row,ensure_ascii=False).encode())
                if len(rows)>=max_rows:reason='row_limit';break
                if used+size>max_bytes:reason='byte_limit';break
                if row['id'] in seen:reason='duplicate_member';break
                rows.append(row);seen.add(row['id']);used+=size
            if reason:break
            after=ids[-1]
            if len(page)<page_size:break
            # REST library owns Retry-After; the outer deadline bounds its retries.
            if deadline-time.monotonic()<=.2:reason='deadline';break
            await asyncio.sleep(.2)
    except TimeoutError:reason='deadline'
    except (KeyError,ValueError,TypeError):reason='invalid_page'
    except asyncio.CancelledError:raise
    except Exception:reason='rest_failed'
    if reason=='rest_failed' and not rows and allow_cached_fallback:
        # Existing cached members only, never a new scrape. Coverage is partial.
        for member in getattr(guild,'members',()):
            row=member_row(member);size=len(json.dumps(row,ensure_ascii=False).encode())
            if len(rows)>=max_rows or used+size>max_bytes:break
            if row['id'] not in seen:rows.append(row);seen.add(row['id']);used+=size
        return ExportResult('cache',str(guild.id),'partial' if rows else 'unknown',rows,'rest_failed_cached_subset')
    expected=getattr(guild,'member_count',None)
    complete=reason is None and type(expected) is int and len(rows)==expected
    return ExportResult('rest',str(guild.id),'complete' if complete else 'partial' if rows else 'unknown',rows,
        reason or (None if complete else 'reported_count_not_matched'))


def _csv_cell(key,value):
    if key=='id':return "'"+str(value)
    if isinstance(value,str) and (value.lstrip()[:1] in ('=','+','-','@') or value[:1] in ('\t','\r','\n')):
        return "'"+value
    return value


def write_exports(result,guild,out_path,*,max_bytes):
    _limits(1,max_bytes)
    if isinstance(result,list):result=ExportResult('provided',str(guild.id),'unknown',result,'unverified_supplied_rows')
    if not isinstance(result,ExportResult) or result.scope!=str(guild.id) or len(result.rows)>MAX_ROWS:
        raise ValueError('invalid_export_result')
    path=Path(out_path).expanduser().absolute()
    if path.suffix.lower()!='.csv':raise ValueError('explicit_csv_path_required')
    sibling=path.with_suffix('.json')
    if path.exists() or path.is_symlink() or sibling.exists() or sibling.is_symlink():raise FileExistsError('output_already_exists')
    parent=path.parent
    if any(part.is_symlink() for part in (parent,*parent.parents)):raise ValueError('symlink_output_parent')
    parent.mkdir(mode=0o700,exist_ok=True)
    if not parent.is_dir() or parent.stat().st_mode&0o077:raise ValueError('private_output_directory_required')
    csv_buffer=io.StringIO(newline='')
    writer=csv.DictWriter(csv_buffer,fieldnames=FIELDS,extrasaction='raise');writer.writeheader()
    writer.writerows({key:_csv_cell(key,value) for key,value in row.items()} for row in result.rows)
    raw_csv=csv_buffer.getvalue().encode()
    raw_json=json.dumps({'guild':{'id':guild.id,'name':guild.name,'member_count':guild.member_count},
        'exported_at':datetime.now(timezone.utc).isoformat(),'source':result.source,'scope':result.scope,
        'coverage':result.coverage,'truncation_reason':result.truncation_reason,'count':len(result.rows),'members':result.rows},
        ensure_ascii=False,indent=2).encode()
    if len(raw_csv)+len(raw_json)>max_bytes:raise ValueError('output_byte_limit')
    if os.name!='posix':raise ValueError('private_posix_output_required')
    flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW
    parent_fd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:
        original=os.fstat(parent_fd);current=parent.stat(follow_symlinks=False)
        if (original.st_dev,original.st_ino)!=(current.st_dev,current.st_ino) or original.st_mode&0o077:
            raise ValueError('output_parent_changed')
        with ExitStack() as handles:
            csv_handle=handles.enter_context(os.fdopen(os.open(path.name,flags,0o600,dir_fd=parent_fd),'wb'))
            json_handle=handles.enter_context(os.fdopen(os.open(sibling.name,flags,0o600,dir_fd=parent_fd),'wb'))
            # On failure retain partial evidence, with both descriptors closed.
            for handle,raw in ((csv_handle,raw_csv),(json_handle,raw_json)):
                handle.write(raw);handle.flush();os.fsync(handle.fileno())
    finally:os.close(parent_fd)
    return path,sibling


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description='Manual private member export; no joins/scrapes')
    target=parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--guild-id',type=int);target.add_argument('--guild-name')
    parser.add_argument('--account-id',required=True)
    parser.add_argument('--out',required=True)
    parser.add_argument('--max-rows',required=True,type=int)
    parser.add_argument('--max-bytes',required=True,type=int)
    parser.add_argument('--timeout',required=True,type=float)
    parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--allow-cached-fallback',action='store_true')
    args=parser.parse_args(argv);_limits(args.max_rows,args.max_bytes)
    if not 0<args.timeout<=300:parser.error('timeout must be 0–300 seconds')
    if args.guild_id is not None and args.guild_id<=0:parser.error('positive guild ID required')
    if not args.account_id.isdecimal() or int(args.account_id)<=0:parser.error('positive account ID required')
    return args


def main(argv=None):
    args=parse_args(argv)
    # Import auth only after explicit CLI validation; imports/tests never read .env.
    import discord
    from core.auth_handler import AuthHandler
    from core.config import Config
    auth=AuthHandler(Config())
    if not auth.is_token_auth():raise SystemExit('token auth required')
    client=discord.Client(chunk_guilds_at_startup=False)
    started=False
    failed=False
    @client.event
    async def on_ready():
        nonlocal started,failed
        if started:return
        started=True
        try:
            verify_identity(client,args.account_id)
            guild=await resolve_guild(client,args)
            result=await fetch_all_members(client,guild,max_rows=args.max_rows,max_bytes=args.max_bytes,
                deadline=time.monotonic()+args.timeout,allow_cached_fallback=args.allow_cached_fallback)
            print(f'coverage={result.coverage}; source={result.source}; rows={len(result.rows)}; reason={result.truncation_reason}')
            if not result.rows or result.coverage!='complete' and not args.allow_partial:raise ValueError('partial_export_requires_explicit_acceptance')
            write_exports(result,guild,args.out,max_bytes=args.max_bytes)
        except (ValueError,OSError):
            failed=True
            print('Export refused or incomplete; existing files preserved. Review limits, identity and private output directory.',file=sys.stderr)
        finally:await client.close()
    client.run(auth.get_token())
    return 1 if failed else 0


if __name__=='__main__':raise SystemExit(main())
