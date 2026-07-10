"""
Extract 2nd posts (H) from CMV Reddit data.

For each pair in pairs.jsonl:
  - org_auth = submission.author  (original post author)
  - d_id     = delta_comment.comments[0].id  (delta comment id)

In threads.jsonl:
  - Find comment c where c.parent_id == "t1_" + d_id  AND  c.author == org_auth
  - These comments {c} are the 2nd posts H
  
Reddit fullname prefixes:
  t1_ = Comment, t3_ = Submission/Post
  So parent_id = "t1_<d_id>" means "this comment is a reply to comment <d_id>"
"""

import json
import bz2
import sys
import os
from collections import defaultdict

def load_pairs(pairs_path):
    """
    Load pairs.jsonl and extract (org_auth, d_id, submission_id) tuples.
    Returns:
        lookup: dict mapping d_id -> list of org_auth values
        pair_records: list of dicts with pair metadata
    """
    # d_id -> list of org_auth (in case multiple pairs share the same delta comment)
    lookup = defaultdict(list)
    pair_records = []
    
    with open(pairs_path, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                pair = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[WARN] Skipping pairs.jsonl line {line_num}: {e}", file=sys.stderr)
                continue
            
            org_auth = pair['submission']['author']
            submission_id = pair['submission']['id']  # e.g. "t3_4gdj35"
            
            # delta_comment has 'comments' list; take the first (and usually only) one
            delta_comments = pair['delta_comment']['comments']
            for dc in delta_comments:
                d_id = dc['id']  # e.g. "d2goctk" (no t1_ prefix in the id field)
                
                lookup[d_id].append(org_auth)
                pair_records.append({
                    'org_auth': org_auth,
                    'submission_id': submission_id,
                    'd_id': d_id,
                    'delta_author': pair['delta_comment']['author'],
                })
    
    return lookup, pair_records


def search_comments_recursive(comments, target_parent_ids, lookup, results):
    """
    Recursively search through the comment tree.
    
    Args:
        comments: list of comment dicts (may have 'children')
        target_parent_ids: set of "t1_<d_id>" strings we're looking for
        lookup: dict mapping d_id -> list of org_auth
        results: list to append matching comments to
    """
    for comment in comments:
        parent_id = comment.get('parent_id', '')
        author = comment.get('author', '')
        
        # Check if this comment's parent_id matches any target
        if parent_id in target_parent_ids:
            # Extract d_id from parent_id: "t1_<d_id>" -> "<d_id>"
            d_id = parent_id[3:]  # strip "t1_"
            
            # Check if the author matches the original post author
            if d_id in lookup and author in lookup[d_id]:
                results.append({
                    'comment_id': comment.get('id'),
                    'author': author,
                    'parent_id': parent_id,
                    'd_id': d_id,
                    'body': comment.get('body', ''),
                    'created_utc': comment.get('created_utc'),
                    'link_id': comment.get('link_id', ''),
                    'score': comment.get('score'),
                    'subreddit': comment.get('subreddit', ''),
                })
        
        # Recurse into children
        children = comment.get('children', [])
        if children:
            search_comments_recursive(children, target_parent_ids, lookup, results)


def extract_second_posts(pairs_path, threads_path, output_path):
    """Main extraction pipeline."""
    
    print("=" * 60)
    print("Extracting 2nd posts (H) from CMV data")
    print("=" * 60)
    
    # Step 1: Load pairs
    print("\n[1/3] Loading pairs.jsonl ...")
    lookup, pair_records = load_pairs(pairs_path)
    print(f"  Loaded {len(pair_records)} pairs")
    print(f"  Unique delta comment IDs: {len(lookup)}")
    
    # Build the set of target parent_ids: "t1_<d_id>"
    target_parent_ids = set(f"t1_{d_id}" for d_id in lookup.keys())
    print(f"  Target parent_ids to search for: {len(target_parent_ids)}")
    
    # Step 2: Search threads
    print(f"\n[2/3] Searching threads.jsonl.bz2 ...")
    results = []
    thread_count = 0
    
    open_func = bz2.open if threads_path.endswith('.bz2') else open
    
    with open_func(threads_path, 'rt', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                thread = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"  [WARN] Skipping threads line {line_num}: {e}", file=sys.stderr)
                continue
            
            thread_count += 1
            
            # Search all comments in this thread
            comments = thread.get('comments', [])
            if comments:
                search_comments_recursive(comments, target_parent_ids, lookup, results)
            
            if thread_count % 5000 == 0:
                print(f"  Processed {thread_count} threads, found {len(results)} matches so far ...")
    
    print(f"  Total threads processed: {thread_count}")
    print(f"  Total 2nd posts (H) found: {len(results)}")
    
    # Step 3: Write output
    print(f"\n[3/3] Writing results to {output_path} ...")
    with open(output_path, 'w', encoding='utf-8') as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    
    print(f"  Written {len(results)} records")
    
    # Summary stats
    matched_d_ids = set(r['d_id'] for r in results)
    unmatched = set(lookup.keys()) - matched_d_ids
    print(f"\n{'=' * 60}")
    print(f"SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Pairs loaded:            {len(pair_records)}")
    print(f"  Unique delta comment IDs: {len(lookup)}")
    print(f"  Matched (found H):       {len(matched_d_ids)}")
    print(f"  Unmatched (no H found):  {len(unmatched)}")
    print(f"  Total 2nd posts (H):     {len(results)}")
    
    # Show a few examples
    if results:
        print(f"\nFirst 3 examples:")
        for r in results[:3]:
            print(f"  org_auth={r['author']}, d_id={r['d_id']}, "
                  f"comment_id={r['comment_id']}, "
                  f"body_preview={r['body'][:80]}...")
    
    return results


if __name__ == '__main__':
    pairs_path = os.path.join(os.path.dirname(__file__), 'pairs.jsonl')
    threads_path = os.path.join(os.path.dirname(__file__), 'threads.jsonl.bz2')
    output_path = os.path.join(os.path.dirname(__file__), 'second_posts_H.jsonl')
    
    extract_second_posts(pairs_path, threads_path, output_path)
